//! Rust EventBus candidate behind the language-neutral signal contract.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Condvar, Mutex as StdMutex, MutexGuard, PoisonError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::contract::{EventBusStats, JsonObject, Signal};

/// Callback value accepted by the Rust EventBus adapter.
pub type Callback = Arc<dyn Fn(&Signal) + Send + Sync + 'static>;

const BUILTIN_SIGNAL_TYPES: &[&str] = &[
    "TASK_ASSIGN",
    "TASK_CANCEL",
    "REVIEW_RESULT",
    "CONSTITUTION_UPDATE",
    "TASK_DONE",
    "TASK_ACCEPT",
    "TASK_ERROR",
    "DISPUTE_RAISE",
    "AGENT_CRASH",
    "STATE_CHANGE",
    "CROSS_REVIEW_REQ",
    "CROSS_REVIEW_RESP",
    "TERRITORY_QUERY",
    "SCOUT_DONE",
    "REVIEW_REQUESTED",
    "TOKEN_USAGE",
    "FILE_CHANGED",
    "CARD_PENDING",
    "APPROVAL_REQUIRED",
    "APPROVAL_RESPONDED",
];

/// Explicit deployment values for the EventBus mechanism.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventBusConfig {
    /// Maximum history records retained.
    pub max_history: usize,
    /// Number of callback worker threads.
    pub workers: usize,
    /// Maximum callbacks in flight, including active callbacks.
    pub max_queued: usize,
    /// Maximum custom signal names retained.
    pub registry_max: usize,
}

/// Reason a signal-name registration was rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignalRegistrationError {
    /// The name already denotes a built-in signal.
    BuiltIn,
    /// The bounded custom registry has no remaining capacity.
    Full,
}

impl EventBusConfig {
    /// Build an EventBus configuration without embedding deployment constants.
    pub const fn new(
        max_history: usize,
        workers: usize,
        max_queued: usize,
        registry_max: usize,
    ) -> Self {
        Self {
            max_history,
            workers,
            max_queued,
            registry_max,
        }
    }
}

struct Task {
    callback: Callback,
    signal: Signal,
}

struct QueueInner {
    queue: VecDeque<Task>,
    closed: bool,
    max_queued: usize,
    submitted: u64,
    completed: u64,
    dropped: u64,
    inflight: usize,
}

struct QueueState {
    inner: StdMutex<QueueInner>,
    not_empty: Condvar,
    drained: Condvar,
}

impl QueueState {
    fn new(max_queued: usize) -> Self {
        Self {
            inner: StdMutex::new(QueueInner {
                queue: VecDeque::new(),
                closed: false,
                max_queued,
                submitted: 0,
                completed: 0,
                dropped: 0,
                inflight: 0,
            }),
            not_empty: Condvar::new(),
            drained: Condvar::new(),
        }
    }

    fn lock(&self) -> MutexGuard<'_, QueueInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Publish/subscribe event bus with bounded asynchronous callback delivery.
pub struct EventBus {
    config: EventBusConfig,
    listeners: StdMutex<BTreeMap<String, Vec<Callback>>>,
    wildcard_listeners: StdMutex<Vec<Callback>>,
    history: StdMutex<VecDeque<Signal>>,
    custom_types: StdMutex<BTreeSet<String>>,
    queue: Arc<QueueState>,
    workers: StdMutex<Vec<JoinHandle<()>>>,
}

impl EventBus {
    /// Create a bus and start its bounded callback workers.
    pub fn new(config: EventBusConfig) -> Self {
        let queue = Arc::new(QueueState::new(config.max_queued));
        let worker_count = config.workers.max(1);
        let mut workers = Vec::with_capacity(worker_count);
        for index in 0..worker_count {
            let worker_queue = Arc::clone(&queue);
            let worker_name = format!("evt-rs-{index}");
            let handle = thread::Builder::new()
                .name(worker_name)
                .spawn(move || worker_loop(worker_queue))
                .expect("event worker thread must start");
            workers.push(handle);
        }
        Self {
            config,
            listeners: StdMutex::new(BTreeMap::new()),
            wildcard_listeners: StdMutex::new(Vec::new()),
            history: StdMutex::new(VecDeque::new()),
            custom_types: StdMutex::new(BTreeSet::new()),
            queue,
            workers: StdMutex::new(workers),
        }
    }

    /// Register a typed callback by string name.
    pub fn on_event(&self, event_type: &str, callback: Callback) -> bool {
        if !self.ensure_signal_type(event_type) {
            return false;
        }
        self.listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .entry(event_type.to_owned())
            .or_default()
            .push(callback);
        true
    }

    /// Register a callback for every signal.
    pub fn on_any(&self, callback: Callback) {
        self.wildcard_listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .push(callback);
    }

    /// Remove a callback from one signal type, or all callbacks when absent.
    pub fn off_event(&self, event_type: &str, callback: Option<&Callback>) {
        let mut listeners = self
            .listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if let Some(callback) = callback {
            if let Some(items) = listeners.get_mut(event_type) {
                items.retain(|item| !Arc::ptr_eq(item, callback));
            }
        } else {
            listeners.remove(event_type);
        }
    }

    /// Remove one wildcard callback by identity.
    pub fn off_any(&self, callback: &Callback) {
        let mut listeners = self
            .wildcard_listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        listeners.retain(|item| !Arc::ptr_eq(item, callback));
    }

    /// Emit a signal, recording history synchronously and returning callback count.
    pub fn emit(&self, signal: Signal) -> usize {
        self.append_history(signal.clone());
        let callbacks = self.callbacks_for(&signal.signal_type);
        let count = callbacks.len();
        if self.queue.lock().closed {
            for callback in callbacks {
                safe_call(&callback, &signal);
            }
            return count;
        }
        for callback in callbacks {
            let _ = self.try_submit(Task {
                callback,
                signal: signal.clone(),
            });
        }
        count
    }

    /// Emit a string event, degrading to zero when the custom registry is full.
    pub fn emit_event(&self, event_type: &str, data: JsonObject, source: &str) -> usize {
        if !self.ensure_signal_type(event_type) {
            return 0;
        }
        self.emit(Signal {
            signal_type: event_type.to_owned(),
            data,
            sender: source.to_owned(),
            target: String::new(),
            timestamp: now_seconds(),
        })
    }

    /// Return recent signals, optionally filtered by type.
    pub fn history(&self, event_type: Option<&str>, limit: usize) -> Vec<Signal> {
        let history = self.history.lock().unwrap_or_else(PoisonError::into_inner);
        let mut values: Vec<Signal> = history
            .iter()
            .filter(|signal| event_type.is_none_or(|wanted| signal.signal_type == wanted))
            .cloned()
            .collect();
        let start = values.len().saturating_sub(limit);
        values.drain(..start);
        values
    }

    /// Return listener and bounded-queue counters.
    pub fn stats(&self) -> EventBusStats {
        let listeners = self
            .listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let wildcard = self
            .wildcard_listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let history = self.history.lock().unwrap_or_else(PoisonError::into_inner);
        let queue = self.queue.lock();
        EventBusStats {
            signal_types: listeners.len(),
            listeners: listeners.values().map(Vec::len).sum(),
            history: history.len(),
            wildcard_listeners: wildcard.len(),
            queue_max: queue.max_queued,
            queue_depth: queue.inflight,
            submitted: queue.submitted,
            completed: queue.completed,
            dropped: queue.dropped,
        }
    }

    /// Stop accepting work and optionally drain callbacks until a deadline.
    pub fn shutdown(&self, wait: bool, timeout: Option<Duration>) {
        {
            let mut queue = self.queue.lock();
            if !queue.closed {
                queue.closed = true;
                self.queue.not_empty.notify_all();
            }
        }
        if !wait {
            return;
        }
        let deadline = timeout.map(|duration| Instant::now() + duration);
        let mut queue = self.queue.lock();
        while queue.inflight > 0 {
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
                return;
            }
            let (next, timed_out) = self
                .queue
                .drained
                .wait_timeout(queue, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            queue = next;
            if timed_out.timed_out() && queue.inflight > 0 {
                return;
            }
        }
        drop(queue);
        self.join_workers();
    }

    /// Register a custom signal name with explicit rejection reasons.
    pub fn register_signal_type(&self, event_type: &str) -> Result<(), SignalRegistrationError> {
        if BUILTIN_SIGNAL_TYPES.contains(&event_type) {
            return Err(SignalRegistrationError::BuiltIn);
        }
        let mut custom = self
            .custom_types
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if custom.contains(event_type) {
            return Ok(());
        }
        if custom.len() >= self.config.registry_max {
            return Err(SignalRegistrationError::Full);
        }
        custom.insert(event_type.to_owned());
        Ok(())
    }

    fn ensure_signal_type(&self, event_type: &str) -> bool {
        if BUILTIN_SIGNAL_TYPES.contains(&event_type) {
            return true;
        }
        self.register_signal_type(event_type).is_ok()
    }

    fn append_history(&self, signal: Signal) {
        let mut history = self.history.lock().unwrap_or_else(PoisonError::into_inner);
        history.push_back(signal);
        while history.len() > self.config.max_history {
            history.pop_front();
        }
    }

    fn callbacks_for(&self, event_type: &str) -> Vec<Callback> {
        let typed = self
            .listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let wildcard = self
            .wildcard_listeners
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        typed
            .get(event_type)
            .into_iter()
            .flatten()
            .chain(wildcard.iter())
            .cloned()
            .collect()
    }

    fn try_submit(&self, task: Task) -> bool {
        let mut queue = self.queue.lock();
        if queue.closed || queue.inflight >= queue.max_queued {
            queue.dropped = queue.dropped.saturating_add(1);
            return false;
        }
        queue.queue.push_back(task);
        queue.inflight += 1;
        queue.submitted = queue.submitted.saturating_add(1);
        self.queue.not_empty.notify_one();
        true
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

impl Drop for EventBus {
    fn drop(&mut self) {
        self.shutdown(false, None);
    }
}

fn worker_loop(queue: Arc<QueueState>) {
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
                inner = queue
                    .not_empty
                    .wait(inner)
                    .unwrap_or_else(PoisonError::into_inner);
            }
        };
        let Some(task) = task else {
            return;
        };
        safe_call(&task.callback, &task.signal);
        let mut inner = queue.lock();
        inner.completed = inner.completed.saturating_add(1);
        inner.inflight = inner.inflight.saturating_sub(1);
        if inner.inflight == 0 {
            queue.drained.notify_all();
        }
    }
}

fn safe_call(callback: &Callback, signal: &Signal) {
    let _ = catch_unwind(AssertUnwindSafe(|| callback(signal)));
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

#[cfg(test)]
mod tests {
    use super::{Callback, EventBus, EventBusConfig};
    use crate::contract::{EventBusStats, JsonObject, Signal};
    use std::sync::{Arc, Mutex};
    use std::thread;
    use std::time::Duration;

    fn bus() -> EventBus {
        EventBus::new(EventBusConfig::new(8, 2, 16, 2))
    }

    fn signal(event_type: &str) -> Signal {
        Signal {
            signal_type: event_type.to_owned(),
            data: JsonObject::new(),
            sender: String::new(),
            target: String::new(),
            timestamp: 1.0,
        }
    }

    fn callback<F>(function: F) -> Callback
    where
        F: Fn(&Signal) + Send + Sync + 'static,
    {
        Arc::new(function)
    }

    #[test]
    fn records_history_and_dispatches_typed_and_wildcard_callbacks() {
        let bus = bus();
        let calls = Arc::new(Mutex::new(Vec::new()));
        let typed_calls = Arc::clone(&calls);
        assert!(bus.on_event(
            "TASK_DONE",
            callback(move |_| typed_calls.lock().unwrap().push("typed")),
        ));
        let wildcard_calls = Arc::clone(&calls);
        bus.on_any(callback(move |_| {
            wildcard_calls.lock().unwrap().push("wildcard")
        }));
        assert_eq!(bus.emit(signal("TASK_DONE")), 2);
        bus.shutdown(true, Some(Duration::from_secs(1)));
        assert_eq!(bus.history(None, 10).len(), 1);
        assert_eq!(calls.lock().unwrap().len(), 2);
        let stats = bus.stats();
        assert_eq!(stats.completed, 2);
        assert!(stats.clean());
    }

    #[test]
    fn bounded_queue_accounts_drops_without_blocking_emitter() {
        let bus = EventBus::new(EventBusConfig::new(8, 1, 0, 2));
        bus.on_any(callback(|_| thread::sleep(Duration::from_millis(10))));
        assert_eq!(bus.emit(signal("TASK_DONE")), 1);
        let stats = bus.stats();
        assert_eq!(stats.submitted, 0);
        assert_eq!(stats.dropped, 1);
        assert_eq!(stats.queue_depth, 0);
        bus.shutdown(true, Some(Duration::from_secs(1)));
    }

    #[test]
    fn dynamic_registry_is_bounded_and_degrades() {
        let bus = bus();
        assert!(bus.register_signal_type("CUSTOM_A").is_ok());
        assert!(bus.register_signal_type("CUSTOM_B").is_ok());
        assert!(bus.register_signal_type("CUSTOM_C").is_err());
        assert!(bus.register_signal_type("TASK_DONE").is_err());
        assert_eq!(bus.emit_event("CUSTOM_C", JsonObject::new(), "test"), 0);
        bus.shutdown(true, Some(Duration::from_secs(1)));
    }

    #[test]
    fn shutdown_is_idempotent_and_post_shutdown_emit_is_synchronous() {
        let bus = bus();
        let calls = Arc::new(Mutex::new(0));
        let observed = Arc::clone(&calls);
        bus.on_any(callback(move |_| *observed.lock().unwrap() += 1));
        bus.shutdown(false, None);
        bus.shutdown(true, Some(Duration::from_secs(1)));
        assert_eq!(bus.emit(signal("TASK_DONE")), 1);
        assert_eq!(*calls.lock().unwrap(), 1);
    }

    #[test]
    fn history_filter_and_stats_shape_match_contract() {
        let bus = bus();
        bus.emit(signal("SCOUT_DONE"));
        bus.emit(signal("TASK_DONE"));
        assert_eq!(bus.history(Some("SCOUT_DONE"), 10).len(), 1);
        let stats: EventBusStats = bus.stats();
        assert_eq!(stats.history, 2);
        assert_eq!(stats.drop_rate(), 0.0);
        bus.shutdown(true, Some(Duration::from_secs(1)));
    }
}
