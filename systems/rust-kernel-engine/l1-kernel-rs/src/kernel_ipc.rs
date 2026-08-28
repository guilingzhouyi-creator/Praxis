//! Rust candidate for the bounded lock IPC channel and registry.

use std::collections::{BTreeMap, VecDeque};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, OnceLock, PoisonError};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Default priority used by lock messages.
pub const IPC_DEFAULT_PRIORITY: f64 = 5.0;
/// Generated message-id width retained by the Python IPC contract.
pub const IPC_MSG_ID_LENGTH: usize = 12;
/// Default request/response wait bound.
pub const IPC_REQUEST_TIMEOUT: Duration = Duration::from_secs(5);
/// Maximum historical pending-message backlog retained by one channel.
pub const IPC_CHANNEL_PENDING_MAX: usize = 128;

static NEXT_MESSAGE_ID: AtomicU64 = AtomicU64::new(1);

/// Operation carried by a lock-channel message.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum LockOp {
    /// Request ownership of a lock.
    Acquire,
    /// Release ownership of a lock.
    Release,
    /// Ask for the current lock status.
    Status,
    /// Request priority inheritance or boosting.
    Boost,
}

/// Message value exchanged through a lock channel.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LockMessage {
    /// Lock operation.
    pub op: LockOp,
    /// Named synchronization primitive addressed by this message.
    pub lock_name: String,
    /// Requesting agent identity.
    #[serde(default)]
    pub agent_id: String,
    /// Scheduling priority attached to the request.
    #[serde(default = "default_priority")]
    pub priority: f64,
    /// Optional response routing identity.
    #[serde(default)]
    pub reply_to: String,
    /// Wall-clock timestamp retained for wire parity.
    #[serde(default = "unix_timestamp")]
    pub timestamp: f64,
    /// Bounded unique request identity.
    #[serde(default = "next_message_id")]
    pub msg_id: String,
}

impl LockMessage {
    /// Construct a message with Python-compatible defaults.
    pub fn new(op: LockOp, lock_name: impl Into<String>) -> Self {
        Self {
            op,
            lock_name: lock_name.into(),
            agent_id: String::new(),
            priority: IPC_DEFAULT_PRIORITY,
            reply_to: String::new(),
            timestamp: unix_timestamp(),
            msg_id: next_message_id(),
        }
    }

    /// Set the requesting agent identity.
    pub fn with_agent(mut self, agent_id: impl Into<String>) -> Self {
        self.agent_id = agent_id.into();
        self
    }

    /// Set the response routing identity.
    pub fn with_reply_to(mut self, reply_to: impl Into<String>) -> Self {
        self.reply_to = reply_to.into();
        self
    }

    /// Set the scheduling priority.
    pub fn with_priority(mut self, priority: f64) -> Self {
        self.priority = priority;
        self
    }
}

fn default_priority() -> f64 {
    IPC_DEFAULT_PRIORITY
}

fn unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

/// Allocate the next monotonic message id, masked to the wire width.
fn next_message_id() -> String {
    let value = NEXT_MESSAGE_ID.fetch_add(1, Ordering::Relaxed) & 0x000f_ffff_ffff_ffff;
    format!("{value:0IPC_MSG_ID_LENGTH$x}")
}

type Handler = Arc<dyn Fn(&LockMessage) -> Option<Value> + Send + Sync + 'static>;

struct ChannelState {
    queue: VecDeque<LockMessage>,
    responses: BTreeMap<String, Value>,
    handlers: Vec<Handler>,
    handler_panics: u64,
}

/// Thread-safe bounded channel dedicated to one synchronization primitive.
pub struct LockChannel {
    /// Public channel name used by the lock registry.
    pub name: String,
    max_pending: usize,
    state: Mutex<ChannelState>,
    response_ready: Condvar,
}

impl LockChannel {
    /// Create a channel with the default historical backlog bound.
    pub fn new(name: impl Into<String>) -> Self {
        Self::with_capacity(name, IPC_CHANNEL_PENDING_MAX)
    }

    /// Create a channel with an explicit backlog bound.
    pub fn with_capacity(name: impl Into<String>, max_pending: usize) -> Self {
        Self {
            name: name.into(),
            max_pending,
            state: Mutex::new(ChannelState {
                queue: VecDeque::new(),
                responses: BTreeMap::new(),
                handlers: Vec::new(),
                handler_panics: 0,
            }),
            response_ready: Condvar::new(),
        }
    }

    /// Send a message and synchronously notify all registered handlers.
    pub fn send(&self, message: LockMessage) -> String {
        let handlers = {
            let mut state = self.lock_state();
            state.queue.push_back(message.clone());
            self.trim_backlog(&mut state);
            state.handlers.clone()
        };

        for handler in handlers {
            let reply = match catch_unwind(AssertUnwindSafe(|| handler(&message))) {
                Ok(reply) => reply,
                Err(_) => {
                    let mut state = self.lock_state();
                    state.handler_panics = state.handler_panics.saturating_add(1);
                    None
                }
            };
            if let Some(reply) = reply {
                self.respond(&message.msg_id, reply);
            }
        }
        message.msg_id
    }

    /// Wait for a response or return an empty JSON object after the deadline.
    pub fn request(&self, message: LockMessage, timeout: Option<Duration>) -> Value {
        let deadline = timeout.map(|duration| std::time::Instant::now() + duration);
        let mut state = self.lock_state();
        state.queue.push_back(message.clone());
        self.trim_backlog(&mut state);

        loop {
            if let Some(response) = state.responses.remove(&message.msg_id) {
                self.remove_message(&mut state, &message.msg_id);
                return response;
            }

            let Some(deadline) = deadline else {
                state = self
                    .response_ready
                    .wait(state)
                    .unwrap_or_else(PoisonError::into_inner);
                continue;
            };
            let remaining = deadline.saturating_duration_since(std::time::Instant::now());
            if remaining.is_zero() {
                self.remove_message(&mut state, &message.msg_id);
                state.responses.remove(&message.msg_id);
                return empty_object();
            }
            let (next, timed_out) = self
                .response_ready
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next;
            if timed_out.timed_out() && !state.responses.contains_key(&message.msg_id) {
                self.remove_message(&mut state, &message.msg_id);
                state.responses.remove(&message.msg_id);
                return empty_object();
            }
        }
    }

    /// Store a response and wake request waiters.
    pub fn respond(&self, message_id: &str, data: Value) {
        let mut state = self.lock_state();
        state.responses.insert(message_id.to_owned(), data);
        self.trim_backlog(&mut state);
        self.response_ready.notify_all();
    }

    /// Register a handler invoked by subsequent `send` calls.
    pub fn register_handler<F>(&self, handler: F)
    where
        F: Fn(&LockMessage) -> Option<Value> + Send + Sync + 'static,
    {
        self.lock_state().handlers.push(Arc::new(handler));
    }

    /// Return the retained historical message count.
    pub fn pending_count(&self) -> usize {
        self.lock_state().queue.len()
    }

    /// Return the number of handler panics contained by this channel.
    ///
    /// This Rust-only diagnostic does not alter the shared IPC stats shape.
    pub fn handler_panics(&self) -> u64 {
        self.lock_state().handler_panics
    }

    fn lock_state(&self) -> std::sync::MutexGuard<'_, ChannelState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Drop oldest queued messages beyond the pending bound, fail-closed under pressure.
    fn trim_backlog(&self, state: &mut ChannelState) {
        while state.queue.len() > self.max_pending {
            state.queue.pop_front();
        }
    }

    /// Remove one queued message by id, ignoring unknown ids.
    fn remove_message(&self, state: &mut ChannelState, message_id: &str) {
        if let Some(index) = state
            .queue
            .iter()
            .position(|message| message.msg_id == message_id)
        {
            state.queue.remove(index);
        }
    }
}

fn empty_object() -> Value {
    Value::Object(Map::new())
}

/// Central named registry for lock channels.
pub struct LockBus {
    channels: Mutex<BTreeMap<String, Arc<LockChannel>>>,
}

impl LockBus {
    /// Create an empty lock bus.
    pub fn new() -> Self {
        Self {
            channels: Mutex::new(BTreeMap::new()),
        }
    }

    /// Return a named channel, creating it on first access.
    pub fn get_channel(&self, name: impl Into<String>) -> Arc<LockChannel> {
        let name = name.into();
        let mut channels = self.channels.lock().unwrap_or_else(PoisonError::into_inner);
        Arc::clone(
            channels
                .entry(name.clone())
                .or_insert_with(|| Arc::new(LockChannel::new(name))),
        )
    }

    /// Return whether a channel has been registered.
    pub fn channel_exists(&self, name: &str) -> bool {
        self.channels
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .contains_key(name)
    }

    /// Return channel names and retained message counts in stable order.
    pub fn stats(&self) -> BTreeMap<String, usize> {
        self.channels
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .iter()
            .map(|(name, channel)| (name.clone(), channel.pending_count()))
            .collect()
    }
}

impl Default for LockBus {
    /// Create a default, empty lock bus.
    fn default() -> Self {
        Self::new()
    }
}

static GLOBAL_LOCK_BUS: OnceLock<Mutex<Option<Arc<LockBus>>>> = OnceLock::new();

/// Initialize the process-wide lock-bus slot on first use.
fn global_lock_bus() -> &'static Mutex<Option<Arc<LockBus>>> {
    GLOBAL_LOCK_BUS.get_or_init(|| Mutex::new(None))
}

/// Return the process-global lock bus singleton.
pub fn get_lock_bus() -> Arc<LockBus> {
    let mut bus = global_lock_bus()
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    Arc::clone(bus.get_or_insert_with(|| Arc::new(LockBus::new())))
}

/// Reset the process-global lock bus for test isolation or hot restart.
pub fn reset_lock_bus() {
    *global_lock_bus()
        .lock()
        .unwrap_or_else(PoisonError::into_inner) = None;
}
