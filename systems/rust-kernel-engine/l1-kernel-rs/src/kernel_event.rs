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
    /// Bounded per-type history length.
    pub max_history: usize,
    /// Number of callback worker threads.
    /// Dispatch worker threads.
    pub workers: usize,
    /// Maximum callbacks in flight, including active callbacks.
    /// Dispatch queue capacity before drops.
    pub max_queued: usize,
    /// Maximum custom signal names retained.
    /// Dynamic signal-registry capacity.
    pub registry_max: usize,
}

/// Reason a signal-name registration was rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignalRegistrationError {
    /// The signal name is empty or whitespace-only.
    InvalidName,
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
    active_channels: BTreeSet<String>,
    closed: bool,
    max_queued: usize,
    submitted: u64,
    completed: u64,
    dropped: u64,
    callback_panics: u64,
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
                active_channels: BTreeSet::new(),
                closed: false,
                max_queued,
                submitted: 0,
                completed: 0,
                dropped: 0,
                callback_panics: 0,
                inflight: 0,
            }),
            not_empty: Condvar::new(),
            drained: Condvar::new(),
        }
    }

    fn lock(&self) -> MutexGuard<'_, QueueInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn record_callback_panic(&self) {
        let mut inner = self.lock();
        inner.callback_panics = inner.callback_panics.saturating_add(1);
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
                if !safe_call(&callback, &signal) {
                    self.queue.record_callback_panic();
                }
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

    /// Return the number of callback panics contained by this bus.
    ///
    /// This Rust-only diagnostic remains separate from the shared
    /// `EventBusStats` value so the Python parity shape is unchanged.
    pub fn callback_panics(&self) -> u64 {
        self.queue.lock().callback_panics
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
    ///
    /// # Errors
    ///
    /// InvalidName for an empty name; BuiltIn when shadowing a built-in
    /// signal; Full at registry capacity.
    pub fn register_signal_type(&self, event_type: &str) -> Result<(), SignalRegistrationError> {
        if event_type.trim().is_empty() {
            return Err(SignalRegistrationError::InvalidName);
        }
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
                if let Some(task) = pop_dispatchable(&mut inner) {
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
        let callback_panicked = !safe_call(&task.callback, &task.signal);
        let mut inner = queue.lock();
        if callback_panicked {
            inner.callback_panics = inner.callback_panics.saturating_add(1);
        }
        inner.active_channels.remove(&task.signal.signal_type);
        inner.completed = inner.completed.saturating_add(1);
        inner.inflight = inner.inflight.saturating_sub(1);
        queue.not_empty.notify_all();
        if inner.inflight == 0 {
            queue.drained.notify_all();
        }
    }
}

fn pop_dispatchable(inner: &mut QueueInner) -> Option<Task> {
    let index = inner
        .queue
        .iter()
        .position(|task| !inner.active_channels.contains(&task.signal.signal_type))?;
    let task = inner.queue.remove(index)?;
    inner
        .active_channels
        .insert(task.signal.signal_type.clone());
    Some(task)
}

fn safe_call(callback: &Callback, signal: &Signal) -> bool {
    catch_unwind(AssertUnwindSafe(|| callback(signal))).is_ok()
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}
