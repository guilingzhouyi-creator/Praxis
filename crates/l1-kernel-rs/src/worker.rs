//! Rust bounded worker-pool candidate behind the WorkerPort contract.

use std::collections::{BTreeMap, VecDeque};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Condvar, Mutex as StdMutex, MutexGuard, PoisonError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::{Value, json};

/// Dictionary-shaped result retained for the WorkerPort adapter.
pub type WireMap = std::collections::BTreeMap<String, Value>;

/// Task closure accepted by the worker mechanism; arguments are already bound.
pub type TaskFn = Box<dyn FnOnce() -> Result<Value, String> + Send + 'static>;

/// Explicit worker-pool deployment values.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WorkerConfig {
    /// Minimum resident workers.
    pub min_workers: usize,
    /// Maximum resident workers.
    pub max_workers: usize,
    /// Maximum pending tasks, excluding active tasks.
    pub queue_size: usize,
    /// Idle wait before an above-floor worker retires.
    pub idle_timeout: Duration,
}

impl WorkerConfig {
    /// Build worker configuration from explicit deployment values.
    pub fn new(
        min_workers: usize,
        max_workers: usize,
        queue_size: usize,
        idle_timeout: Duration,
    ) -> Self {
        Self {
            min_workers,
            max_workers: max_workers.max(min_workers),
            queue_size,
            idle_timeout,
        }
    }
}

/// Error returned while waiting for a task result.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TaskHandleError {
    /// The task did not finish before the supplied deadline.
    Timeout,
    /// The task failed or was evicted before execution.
    Failed(String),
}

struct TaskState {
    result: StdMutex<Option<Result<Value, String>>>,
    ready: Condvar,
}

/// Result handle for a submitted task.
#[derive(Clone)]
pub struct TaskHandle {
    state: Arc<TaskState>,
}

impl TaskHandle {
    fn new() -> Self {
        Self {
            state: Arc::new(TaskState {
                result: StdMutex::new(None),
                ready: Condvar::new(),
            }),
        }
    }

    /// Return whether the task has completed.
    pub fn done(&self) -> bool {
        self.state
            .result
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .is_some()
    }

    /// Wait for and return the task value, or a structured failure.
    pub fn result(&self, timeout: Option<Duration>) -> Result<Value, TaskHandleError> {
        let deadline = timeout.map(|duration| Instant::now() + duration);
        let mut result = self
            .state
            .result
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        while result.is_none() {
            let Some(deadline) = deadline else {
                result = self
                    .state
                    .ready
                    .wait(result)
                    .unwrap_or_else(PoisonError::into_inner);
                continue;
            };
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(TaskHandleError::Timeout);
            }
            let (next, timed_out) = self
                .state
                .ready
                .wait_timeout(result, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            result = next;
            if timed_out.timed_out() && result.is_none() {
                return Err(TaskHandleError::Timeout);
            }
        }
        match result.as_ref().expect("result checked above") {
            Ok(value) => Ok(value.clone()),
            Err(error) => Err(TaskHandleError::Failed(error.clone())),
        }
    }

    fn complete(&self, result: Result<Value, String>) {
        let mut slot = self
            .state
            .result
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if slot.is_none() {
            *slot = Some(result);
            self.state.ready.notify_all();
        }
    }
}

struct Task {
    action: Option<TaskFn>,
    handle: Option<TaskHandle>,
}

struct QueueInner {
    queue: VecDeque<Task>,
    closed: bool,
}

struct QueueState {
    capacity: usize,
    inner: StdMutex<QueueInner>,
    not_empty: Condvar,
    drained: Condvar,
}

impl QueueState {
    fn new(capacity: usize) -> Self {
        Self {
            capacity,
            inner: StdMutex::new(QueueInner {
                queue: VecDeque::with_capacity(capacity),
                closed: false,
            }),
            not_empty: Condvar::new(),
            drained: Condvar::new(),
        }
    }

    fn lock(&self) -> MutexGuard<'_, QueueInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[derive(Debug, Default)]
struct Metrics {
    pool_size: usize,
    active: usize,
    completed: u64,
    rejected: u64,
}

/// Bounded worker pool with FIFO eviction and idle shrink.
pub struct WorkerPool {
    config: WorkerConfig,
    queue: Arc<QueueState>,
    metrics: Arc<StdMutex<Metrics>>,
    workers: StdMutex<Vec<JoinHandle<()>>>,
}

impl WorkerPool {
    /// Create a worker pool and start the configured minimum workers.
    pub fn new(config: WorkerConfig) -> Result<Self, &'static str> {
        if config.min_workers == 0 {
            return Err("minimum worker count must be at least one");
        }
        if config.queue_size == 0 {
            return Err("worker queue capacity must be at least one");
        }
        let queue = Arc::new(QueueState::new(config.queue_size));
        let metrics = Arc::new(StdMutex::new(Metrics::default()));
        let pool = Self {
            config,
            queue,
            metrics,
            workers: StdMutex::new(Vec::new()),
        };
        for _ in 0..config.min_workers {
            pool.add_worker();
        }
        Ok(pool)
    }

    /// Submit a fire-and-forget task, evicting the oldest pending task if full.
    pub fn submit(&self, action: TaskFn) -> WireMap {
        self.enqueue(action, None)
    }

    /// Submit a task and return a handle that always completes or fails.
    pub fn submit_result(&self, action: TaskFn) -> TaskHandle {
        let handle = TaskHandle::new();
        let result = self.enqueue(action, Some(handle.clone()));
        if result.get("success") != Some(&json!(true)) {
            handle.complete(Err(result
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("task rejected")
                .to_owned()));
        }
        handle
    }

    /// Stop accepting tasks and optionally drain the queue before joining workers.
    pub fn shutdown(&self, wait: bool, timeout: Option<Duration>) -> WireMap {
        {
            let mut queue = self.queue.lock();
            if !queue.closed {
                queue.closed = true;
                self.queue.not_empty.notify_all();
            }
        }
        if !wait {
            return ok([("shutdown", json!(true))]);
        }
        let deadline = timeout.map(|duration| Instant::now() + duration);
        loop {
            let queue_empty = self.queue.lock().queue.is_empty();
            let active = self.metrics_lock().active;
            if queue_empty && active == 0 {
                break;
            }
            let mut queue = self.queue.lock();
            let Some(deadline) = deadline else {
                queue = self
                    .queue
                    .drained
                    .wait(queue)
                    .unwrap_or_else(PoisonError::into_inner);
                continue;
            };
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return fail("shutdown timeout", []);
            }
            let (next, timed_out) = self
                .queue
                .drained
                .wait_timeout(queue, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            queue = next;
            if timed_out.timed_out() {
                let queue_pending = !queue.queue.is_empty();
                drop(queue);
                let active = self.metrics_lock().active;
                if queue_pending || active > 0 {
                    return fail("shutdown timeout", []);
                }
            }
        }
        self.join_workers();
        ok([("shutdown", json!(true))])
    }

    /// Return sizing, activity, queue, completion, rejection, and shutdown counters.
    pub fn stats(&self) -> WireMap {
        let metrics = self.metrics_lock();
        let queue = self.queue.lock();
        BTreeMap::from([
            ("pool_size".to_owned(), json!(metrics.pool_size)),
            ("active".to_owned(), json!(metrics.active)),
            ("queued".to_owned(), json!(queue.queue.len())),
            ("completed".to_owned(), json!(metrics.completed)),
            ("rejected".to_owned(), json!(metrics.rejected)),
            ("min".to_owned(), json!(self.config.min_workers)),
            ("max".to_owned(), json!(self.config.max_workers)),
            ("shutdown".to_owned(), json!(queue.closed)),
        ])
    }

    fn enqueue(&self, action: TaskFn, handle: Option<TaskHandle>) -> WireMap {
        let mut queue = self.queue.lock();
        if queue.closed {
            drop(queue);
            let mut metrics = self.metrics_lock();
            metrics.rejected = metrics.rejected.saturating_add(1);
            return fail("pool is shut down", []);
        }
        let mut rejected = false;
        if queue.queue.len() >= self.queue.capacity {
            if let Some(mut evicted) = queue.queue.pop_front() {
                if let Some(evicted_handle) = evicted.handle.take() {
                    evicted_handle.complete(Err("task evicted by backpressure".to_owned()));
                }
                rejected = true;
            } else {
                drop(queue);
                let mut metrics = self.metrics_lock();
                metrics.rejected = metrics.rejected.saturating_add(1);
                return fail("queue full and eviction failed", []);
            }
        }
        queue.queue.push_back(Task {
            action: Some(action),
            handle,
        });
        let queued = queue.queue.len();
        self.queue.not_empty.notify_one();
        drop(queue);
        if rejected {
            let mut metrics = self.metrics_lock();
            metrics.rejected = metrics.rejected.saturating_add(1);
        }
        let workers = self.metrics_lock().pool_size;
        if workers < self.config.max_workers && queued > workers.saturating_mul(2) {
            self.add_worker();
        }
        ok([("submitted", json!(true))])
    }

    fn add_worker(&self) {
        let mut metrics = self.metrics_lock();
        if metrics.pool_size >= self.config.max_workers {
            return;
        }
        metrics.pool_size += 1;
        drop(metrics);
        let queue = Arc::clone(&self.queue);
        let metrics = Arc::clone(&self.metrics);
        let min_workers = self.config.min_workers;
        let idle_timeout = self.config.idle_timeout;
        let handle = thread::Builder::new()
            .name("worker-rs".to_owned())
            .spawn(move || worker_loop(queue, metrics, min_workers, idle_timeout))
            .expect("worker thread must start");
        self.workers
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .push(handle);
    }

    fn join_workers(&self) {
        let workers =
            std::mem::take(&mut *self.workers.lock().unwrap_or_else(PoisonError::into_inner));
        let current = thread::current().id();
        for worker in workers {
            if worker.thread().id() != current {
                let _ = worker.join();
            }
        }
    }

    fn metrics_lock(&self) -> MutexGuard<'_, Metrics> {
        self.metrics.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Drop for WorkerPool {
    fn drop(&mut self) {
        let mut queue = self.queue.lock();
        queue.closed = true;
        self.queue.not_empty.notify_all();
    }
}

fn worker_loop(
    queue: Arc<QueueState>,
    metrics: Arc<StdMutex<Metrics>>,
    min_workers: usize,
    idle_timeout: Duration,
) {
    loop {
        let task = {
            let mut inner = queue.lock();
            loop {
                if let Some(task) = inner.queue.pop_front() {
                    break Some(task);
                }
                if inner.closed {
                    break None;
                }
                let (next, timed_out) = queue
                    .not_empty
                    .wait_timeout(inner, idle_timeout)
                    .unwrap_or_else(PoisonError::into_inner);
                inner = next;
                if timed_out.timed_out() {
                    drop(inner);
                    let mut counters = metrics.lock().unwrap_or_else(PoisonError::into_inner);
                    if counters.pool_size > min_workers {
                        counters.pool_size -= 1;
                        break None;
                    }
                    drop(counters);
                    inner = queue.lock();
                }
            }
        };
        let Some(mut task) = task else {
            return;
        };
        {
            let mut counters = metrics.lock().unwrap_or_else(PoisonError::into_inner);
            counters.active += 1;
        }
        let result = match task.action.take() {
            Some(action) => catch_unwind(AssertUnwindSafe(action))
                .map_err(|_| "task panicked".to_owned())
                .and_then(|value| value),
            None => Err("task missing action".to_owned()),
        };
        if let Some(handle) = task.handle {
            handle.complete(result);
        }
        let mut counters = metrics.lock().unwrap_or_else(PoisonError::into_inner);
        counters.active = counters.active.saturating_sub(1);
        counters.completed = counters.completed.saturating_add(1);
        if counters.active == 0 {
            queue.drained.notify_all();
        }
        drop(counters);
        let inner = queue.lock();
        if inner.queue.is_empty() {
            queue.drained.notify_all();
        }
    }
}

fn ok<const N: usize>(fields: [(&str, Value); N]) -> WireMap {
    let mut result = std::collections::BTreeMap::from_iter(
        fields
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value)),
    );
    result.insert("success".to_owned(), json!(true));
    result
}

fn fail<const N: usize>(error: &str, fields: [(&str, Value); N]) -> WireMap {
    let mut result = std::collections::BTreeMap::from_iter(
        fields
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value)),
    );
    result.insert("success".to_owned(), json!(false));
    result.insert("error".to_owned(), json!(error));
    result
}

#[cfg(test)]
mod tests {
    use super::{TaskHandleError, WorkerConfig, WorkerPool};
    use serde_json::json;
    use std::sync::{Arc, Mutex};
    use std::thread;
    use std::time::Duration;

    fn pool() -> WorkerPool {
        WorkerPool::new(WorkerConfig::new(1, 2, 4, Duration::from_millis(20))).unwrap()
    }

    #[test]
    fn submit_result_returns_json_and_updates_stats() {
        let pool = pool();
        let handle = pool.submit_result(Box::new(|| Ok(json!({"value": 42}))));
        assert_eq!(
            handle.result(Some(Duration::from_secs(1))).unwrap(),
            json!({"value": 42})
        );
        assert_eq!(
            handle.result(Some(Duration::from_millis(1))).unwrap(),
            json!({"value": 42})
        );
        assert_eq!(pool.stats()["completed"], 1);
        assert_eq!(
            pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
            true
        );
    }

    #[test]
    fn task_failure_and_panic_complete_handles() {
        let pool = pool();
        let failed = pool.submit_result(Box::new(|| Err("explicit failure".to_owned())));
        assert_eq!(
            failed.result(Some(Duration::from_secs(1))),
            Err(TaskHandleError::Failed("explicit failure".to_owned()))
        );
        let panicked = pool.submit_result(Box::new(|| -> Result<_, String> { panic!("boom") }));
        assert_eq!(
            panicked.result(Some(Duration::from_secs(1))),
            Err(TaskHandleError::Failed("task panicked".to_owned()))
        );
        pool.shutdown(true, Some(Duration::from_secs(1)));
    }

    #[test]
    fn full_queue_evicts_oldest_and_completes_evicted_handle() {
        let pool = WorkerPool::new(WorkerConfig::new(1, 1, 1, Duration::from_secs(1))).unwrap();
        let gate = Arc::new(Mutex::new(false));
        let started = Arc::new(Mutex::new(false));
        let hold_gate = Arc::clone(&gate);
        let mark_started = Arc::clone(&started);
        let running = pool.submit_result(Box::new(move || {
            *mark_started.lock().unwrap() = true;
            while !*hold_gate.lock().unwrap() {
                thread::yield_now();
            }
            Ok(json!(0))
        }));
        while !*started.lock().unwrap() {
            thread::yield_now();
        }
        let evicted = pool.submit_result(Box::new(|| Ok(json!(1))));
        let accepted = pool.submit_result(Box::new(|| Ok(json!(2))));
        assert_eq!(
            evicted.result(Some(Duration::from_secs(1))),
            Err(TaskHandleError::Failed(
                "task evicted by backpressure".to_owned()
            ))
        );
        *gate.lock().unwrap() = true;
        assert_eq!(
            running.result(Some(Duration::from_secs(1))).unwrap(),
            json!(0)
        );
        assert_eq!(
            accepted.result(Some(Duration::from_secs(1))).unwrap(),
            json!(2)
        );
        assert_eq!(pool.stats()["rejected"], 1);
        pool.shutdown(true, Some(Duration::from_secs(1)));
    }

    #[test]
    fn shutdown_rejects_future_tasks_and_idle_workers_shrink_to_floor() {
        let pool = pool();
        pool.add_worker();
        assert_eq!(pool.stats()["pool_size"], json!(2));
        let deadline = std::time::Instant::now() + Duration::from_secs(1);
        while pool.stats()["pool_size"] == json!(2) && std::time::Instant::now() < deadline {
            thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(pool.stats()["pool_size"], json!(1));

        let _ = pool.submit(Box::new(|| Ok(json!(1))));
        pool.shutdown(true, Some(Duration::from_secs(1)));
        assert_eq!(pool.submit(Box::new(|| Ok(json!(2))))["success"], false);
    }

    #[test]
    fn shutdown_timeout_and_stats_do_not_invert_lock_order() {
        let pool = std::sync::Arc::new(
            WorkerPool::new(WorkerConfig::new(1, 1, 1, Duration::from_secs(1))).unwrap(),
        );
        let release = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let task_release = Arc::clone(&release);
        let handle = pool.submit_result(Box::new(move || {
            while !task_release.load(std::sync::atomic::Ordering::Acquire) {
                thread::yield_now();
            }
            Ok(json!(7))
        }));
        thread::sleep(Duration::from_millis(5));

        let shutdown_pool = Arc::clone(&pool);
        let shutdown =
            thread::spawn(move || shutdown_pool.shutdown(true, Some(Duration::from_millis(20))));
        for _ in 0..100 {
            let _ = pool.stats();
        }
        assert_eq!(shutdown.join().unwrap()["success"], false);

        release.store(true, std::sync::atomic::Ordering::Release);
        assert_eq!(
            handle.result(Some(Duration::from_secs(1))).unwrap(),
            json!(7)
        );
        assert_eq!(
            pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
            true
        );
    }
}
