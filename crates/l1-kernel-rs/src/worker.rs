//! Rust bounded worker-pool candidate behind the WorkerPort contract.

use std::collections::{BTreeMap, VecDeque};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex as StdMutex, MutexGuard, PoisonError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crate::cancellation::CancellationToken;
use serde_json::{Value, json};

const CLAIM_BATCH_SIZE: usize = 8;

/// Dictionary-shaped result retained for the WorkerPort adapter.
pub type WireMap = std::collections::BTreeMap<String, Value>;

/// Task closure accepted by the worker mechanism; arguments are already bound.
pub type TaskFn = Box<dyn FnOnce() -> Result<Value, String> + Send + 'static>;

/// Explicit worker-pool deployment values.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WorkerConfig {
    /// Minimum resident workers.
    /// Idle floor for the pool size.
    pub min_workers: usize,
    /// Maximum resident workers.
    /// Hard ceiling for the pool size.
    pub max_workers: usize,
    /// Maximum pending tasks, excluding active tasks.
    /// Bounded admission queue capacity.
    pub queue_size: usize,
    /// Idle wait before an above-floor worker retires.
    /// Idle shrink threshold per worker.
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
    /// The task deadline elapsed before or during execution.
    TaskTimeout,
    /// The task failed or was evicted before execution.
    Failed(String),
    /// The task was cancelled before execution began.
    Cancelled(String),
}

struct TaskState {
    result: StdMutex<Option<Result<Value, TaskHandleError>>>,
    ready: Condvar,
    cancellation: CancellationToken,
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
                cancellation: CancellationToken::new(),
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
    ///
    /// # Errors
    ///
    /// Timeout when the caller gives up first; Cancelled / TaskTimeout /
    /// Failed mirror the terminal outcome recorded by the pool.
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
            Err(error) => Err(error.clone()),
        }
    }

    /// Request cancellation before the worker starts this task.
    pub fn cancel(&self, reason: impl Into<String>) -> bool {
        self.state.cancellation.cancel(reason)
    }

    /// Return whether cancellation has been requested for this task.
    pub fn is_cancelled(&self) -> bool {
        self.state.cancellation.is_cancelled()
    }

    /// Return the retained cancellation reason, if any.
    pub fn cancellation_reason(&self) -> Option<String> {
        self.state.cancellation.reason()
    }

    fn complete(&self, result: Result<Value, TaskHandleError>) {
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
    deadline: Option<Instant>,
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
    pool_size: AtomicUsize,
    active: AtomicUsize,
    completed: AtomicU64,
    claim_wait_ns: AtomicU64,
    rejected: AtomicU64,
    outcome_cancelled: AtomicU64,
    outcome_timed_out: AtomicU64,
    outcome_failed: AtomicU64,
}

/// Bounded worker pool with FIFO eviction and idle shrink.
pub struct WorkerPool {
    config: WorkerConfig,
    queue: Arc<QueueState>,
    metrics: Arc<Metrics>,
    workers: StdMutex<Vec<JoinHandle<()>>>,
}

impl WorkerPool {
    /// Create a worker pool and start the configured minimum workers.
    ///
    /// # Errors
    ///
    /// `Err` when the minimum worker count or queue capacity is zero.
    pub fn new(config: WorkerConfig) -> Result<Self, &'static str> {
        if config.min_workers == 0 {
            return Err("minimum worker count must be at least one");
        }
        if config.queue_size == 0 {
            return Err("worker queue capacity must be at least one");
        }
        let queue = Arc::new(QueueState::new(config.queue_size));
        let metrics = Arc::new(Metrics::default());
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
        self.enqueue(action, None, None)
    }

    /// Submit a task and return a handle that always completes or fails.
    pub fn submit_result(&self, action: TaskFn) -> TaskHandle {
        self.submit_result_with_deadline(action, None)
    }

    /// Submit a task with a deadline enforced by the worker boundary.
    pub fn submit_result_with_timeout(&self, action: TaskFn, timeout: Duration) -> TaskHandle {
        self.submit_result_with_deadline(action, Some(deadline_after(timeout)))
    }

    /// Submit a batch of tasks while holding the queue admission lock once.
    ///
    /// Tasks retain the same FIFO, eviction, cancellation, completion, and
    /// shutdown semantics as individual submissions. The batch form only
    /// changes how admission work is grouped; it does not execute closures on
    /// the caller thread.
    pub fn submit_result_batch(&self, actions: Vec<TaskFn>) -> Vec<TaskHandle> {
        let handles = actions
            .iter()
            .map(|_| TaskHandle::new())
            .collect::<Vec<_>>();
        let tasks = actions
            .into_iter()
            .zip(handles.iter().cloned())
            .map(|(action, handle)| Task {
                action: Some(action),
                handle: Some(handle),
                deadline: None,
            })
            .collect::<Vec<_>>();
        let result = self.enqueue_tasks(tasks);
        if result.get("success") != Some(&json!(true)) {
            let error = result
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("task batch rejected")
                .to_owned();
            for handle in &handles {
                handle.complete(Err(TaskHandleError::Failed(error.clone())));
            }
        }
        handles
    }

    /// Submit a batch without evicting already queued work.
    ///
    /// This strict path is used by callers that need all-or-none admission:
    /// the queue is checked and filled under one lock, so a capacity or
    /// shutdown rejection leaves both the existing queue and the new batch
    /// untouched.
    pub fn submit_result_batch_strict(
        &self,
        actions: Vec<TaskFn>,
    ) -> Result<Vec<TaskHandle>, String> {
        if actions.is_empty() {
            return Ok(Vec::new());
        }
        let handles = actions
            .iter()
            .map(|_| TaskHandle::new())
            .collect::<Vec<_>>();
        let tasks = actions
            .into_iter()
            .zip(handles.iter().cloned())
            .map(|(action, handle)| Task {
                action: Some(action),
                handle: Some(handle),
                deadline: None,
            })
            .collect::<Vec<_>>();
        let batch_size = tasks.len();
        let mut queue = self.queue.lock();
        if queue.closed {
            self.metrics
                .rejected
                .fetch_add(batch_size.try_into().unwrap_or(u64::MAX), Ordering::Relaxed);
            return Err("pool is shut down".to_owned());
        }
        if queue.queue.len().saturating_add(batch_size) > self.queue.capacity {
            self.metrics
                .rejected
                .fetch_add(batch_size.try_into().unwrap_or(u64::MAX), Ordering::Relaxed);
            return Err("worker queue capacity is insufficient for batch".to_owned());
        }
        queue.queue.extend(tasks);
        let queued = queue.queue.len();
        self.notify_waiting_workers(batch_size);
        drop(queue);
        self.maybe_grow_worker(queued);
        Ok(handles)
    }

    fn submit_result_with_deadline(&self, action: TaskFn, deadline: Option<Instant>) -> TaskHandle {
        let handle = TaskHandle::new();
        let result = self.enqueue(action, Some(handle.clone()), deadline);
        if result.get("success") != Some(&json!(true)) {
            handle.complete(Err(TaskHandleError::Failed(
                result
                    .get("error")
                    .and_then(Value::as_str)
                    .unwrap_or("task rejected")
                    .to_owned(),
            )));
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
            let active = self.metrics.active.load(Ordering::Acquire);
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
                let active = self.metrics.active.load(Ordering::Acquire);
                if queue_pending || active > 0 {
                    return fail("shutdown timeout", []);
                }
            }
        }
        self.join_workers();
        ok([("shutdown", json!(true))])
    }

    /// Return sizing, activity, queue, completion, outcome, rejection, and shutdown counters.
    pub fn stats(&self) -> WireMap {
        let metrics = &self.metrics;
        let queue = self.queue.lock();
        BTreeMap::from([
            (
                "pool_size".to_owned(),
                json!(metrics.pool_size.load(Ordering::Acquire)),
            ),
            (
                "active".to_owned(),
                json!(metrics.active.load(Ordering::Acquire)),
            ),
            ("queued".to_owned(), json!(queue.queue.len())),
            (
                "completed".to_owned(),
                json!(metrics.completed.load(Ordering::Relaxed)),
            ),
            (
                "queue_wait_ns".to_owned(),
                json!(metrics.claim_wait_ns.load(Ordering::Relaxed)),
            ),
            (
                "rejected".to_owned(),
                json!(metrics.rejected.load(Ordering::Relaxed)),
            ),
            (
                "outcome_cancelled".to_owned(),
                json!(metrics.outcome_cancelled.load(Ordering::Relaxed)),
            ),
            (
                "outcome_timed_out".to_owned(),
                json!(metrics.outcome_timed_out.load(Ordering::Relaxed)),
            ),
            (
                "outcome_failed".to_owned(),
                json!(metrics.outcome_failed.load(Ordering::Relaxed)),
            ),
            ("min".to_owned(), json!(self.config.min_workers)),
            ("max".to_owned(), json!(self.config.max_workers)),
            ("shutdown".to_owned(), json!(queue.closed)),
        ])
    }

    fn enqueue(
        &self,
        action: TaskFn,
        handle: Option<TaskHandle>,
        deadline: Option<Instant>,
    ) -> WireMap {
        self.enqueue_tasks(vec![Task {
            action: Some(action),
            handle,
            deadline,
        }])
    }

    fn enqueue_tasks(&self, tasks: Vec<Task>) -> WireMap {
        if tasks.is_empty() {
            return ok([("submitted", json!(true))]);
        }
        let batch_size = tasks.len();
        let mut queue = self.queue.lock();
        if queue.closed {
            let rejected = tasks.len().try_into().unwrap_or(u64::MAX);
            drop(queue);
            self.metrics.rejected.fetch_add(rejected, Ordering::Relaxed);
            return fail("pool is shut down", []);
        }
        let mut evicted_handles = Vec::new();
        let mut rejected = 0_u64;
        for task in tasks {
            if queue.queue.len() >= self.queue.capacity {
                if let Some(mut evicted) = queue.queue.pop_front() {
                    if let Some(evicted_handle) = evicted.handle.take() {
                        evicted_handles.push(evicted_handle);
                    }
                    rejected = rejected.saturating_add(1);
                } else {
                    drop(queue);
                    self.metrics.rejected.fetch_add(1, Ordering::Relaxed);
                    return fail("queue full and eviction failed", []);
                }
            }
            queue.queue.push_back(task);
        }
        let queued = queue.queue.len();
        self.notify_waiting_workers(batch_size);
        drop(queue);
        for handle in evicted_handles {
            handle.complete(Err(TaskHandleError::Failed(
                "task evicted by backpressure".to_owned(),
            )));
        }
        if rejected > 0 {
            self.metrics.rejected.fetch_add(rejected, Ordering::Relaxed);
        }
        self.maybe_grow_worker(queued);
        ok([("submitted", json!(true))])
    }

    fn maybe_grow_worker(&self, queued: usize) {
        let workers = self.metrics.pool_size.load(Ordering::Acquire);
        if workers < self.config.max_workers && queued > workers.saturating_mul(2) {
            self.add_worker();
        }
    }

    fn notify_waiting_workers(&self, submitted: usize) {
        let worker_count = self.metrics.pool_size.load(Ordering::Acquire).max(1);
        let wake_count = submitted.min(worker_count);
        for _ in 0..wake_count {
            self.queue.not_empty.notify_one();
        }
    }

    fn add_worker(&self) {
        let grew =
            self.metrics
                .pool_size
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |size| {
                    (size < self.config.max_workers).then_some(size + 1)
                });
        if grew.is_err() {
            return;
        }
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
}

impl Drop for WorkerPool {
    fn drop(&mut self) {
        let mut queue = self.queue.lock();
        queue.closed = true;
        self.queue.not_empty.notify_all();
    }
}

fn deadline_after(timeout: Duration) -> Instant {
    Instant::now()
        .checked_add(timeout)
        .unwrap_or_else(Instant::now)
}

fn execute_task(
    action: TaskFn,
    deadline: Option<Instant>,
    handle: Option<&TaskHandle>,
) -> Result<Value, TaskHandleError> {
    if let Some(handle) = handle
        && let Some(reason) = handle.cancellation_reason()
    {
        return Err(TaskHandleError::Cancelled(reason));
    }
    if deadline.is_some_and(|limit| Instant::now() >= limit) {
        return Err(TaskHandleError::TaskTimeout);
    }
    let result = catch_unwind(AssertUnwindSafe(action))
        .map_err(|_| TaskHandleError::Failed("task panicked".to_owned()))
        .and_then(|value| value.map_err(TaskHandleError::Failed));
    if deadline.is_some_and(|limit| Instant::now() >= limit) {
        Err(TaskHandleError::TaskTimeout)
    } else {
        result
    }
}

fn worker_loop(
    queue: Arc<QueueState>,
    metrics: Arc<Metrics>,
    min_workers: usize,
    idle_timeout: Duration,
) {
    let mut batch = Vec::with_capacity(CLAIM_BATCH_SIZE);
    loop {
        if !claim_batch(&queue, &mut batch, &metrics, min_workers, idle_timeout) {
            return;
        }
        for mut task in batch.drain(..) {
            let result = match task.action.take() {
                Some(action) => execute_task(action, task.deadline, task.handle.as_ref()),
                None => Err(TaskHandleError::Failed("task missing action".to_owned())),
            };
            let outcome = match &result {
                Ok(_) => None,
                Err(TaskHandleError::Cancelled(_)) => Some(Outcome::Cancelled),
                Err(TaskHandleError::TaskTimeout) => Some(Outcome::TimedOut),
                Err(TaskHandleError::Timeout | TaskHandleError::Failed(_)) => Some(Outcome::Failed),
            };
            let handle = task.handle;
            let was_last = metrics
                .active
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                    Some(active.saturating_sub(1))
                })
                .is_ok_and(|active| active == 1);
            metrics.completed.fetch_add(1, Ordering::Relaxed);
            match outcome {
                Some(Outcome::Cancelled) => {
                    metrics.outcome_cancelled.fetch_add(1, Ordering::Relaxed);
                }
                Some(Outcome::TimedOut) => {
                    metrics.outcome_timed_out.fetch_add(1, Ordering::Relaxed);
                }
                Some(Outcome::Failed) => {
                    metrics.outcome_failed.fetch_add(1, Ordering::Relaxed);
                }
                None => {}
            }
            if was_last {
                queue.drained.notify_all();
            }
            if let Some(handle) = handle {
                handle.complete(result);
            }
        }
    }
}

fn claim_batch(
    queue: &QueueState,
    batch: &mut Vec<Task>,
    metrics: &Metrics,
    min_workers: usize,
    idle_timeout: Duration,
) -> bool {
    batch.clear();
    let claim_started = Instant::now();
    let mut inner = queue.lock();
    loop {
        if !inner.queue.is_empty() {
            let count = inner.queue.len().min(CLAIM_BATCH_SIZE);
            for _ in 0..count {
                if let Some(task) = inner.queue.pop_front() {
                    batch.push(task);
                }
            }
            metrics.claim_wait_ns.fetch_add(
                claim_started
                    .elapsed()
                    .as_nanos()
                    .try_into()
                    .unwrap_or(u64::MAX),
                Ordering::Relaxed,
            );
            metrics.active.fetch_add(batch.len(), Ordering::AcqRel);
            return true;
        }
        if inner.closed {
            return false;
        }
        let (next, timed_out) = queue
            .not_empty
            .wait_timeout(inner, idle_timeout)
            .unwrap_or_else(PoisonError::into_inner);
        inner = next;
        if timed_out.timed_out() {
            drop(inner);
            let retired =
                metrics
                    .pool_size
                    .fetch_update(Ordering::AcqRel, Ordering::Acquire, |size| {
                        (size > min_workers).then_some(size - 1)
                    });
            if retired.is_ok() {
                return false;
            }
            inner = queue.lock();
        }
    }
}

#[derive(Debug, Clone, Copy)]
enum Outcome {
    Cancelled,
    TimedOut,
    Failed,
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
