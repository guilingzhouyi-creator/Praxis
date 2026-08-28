//! Rust synchronization mechanisms staged behind the Python L1 contract.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Condvar, Mutex as StdMutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use crate::cancellation::CancellationToken;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

/// Dictionary-shaped result kept compatible with Python sync methods.
pub type WireMap = BTreeMap<String, Value>;

/// Priority-inheritance callback invoked when a waiter lowers the holder's priority.
pub type BoostCallback = Arc<dyn Fn(&str, f64, f64) + Send + Sync>;

/// Mutex state exposed by the Python `status()` contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LockState {
    /// No owner and no queued waiters.
    Free,
    /// One owner holds the lock.
    Locked,
    /// An owner holds the lock while one or more agents wait.
    Contended,
}

impl LockState {
    /// Return the stable Python enum spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Free => "FREE",
            Self::Locked => "LOCKED",
            Self::Contended => "CONTENDED",
        }
    }
}

#[derive(Debug, Clone)]
struct Waiter {
    agent_id: String,
    priority: f64,
}

#[derive(Debug)]
struct MutexState {
    owner: String,
    recursion: u32,
    state: LockState,
    effective_priority: f64,
    base_priority: f64,
    waiters: Vec<Waiter>,
}

/// Priority-aware, reentrant mutex candidate for the Rust L1 mechanism layer.
///
/// # Invariants
///
/// - Reentrancy is tracked per owning thread; nested acquisitions must be
///   released in matching pairs.
/// - Waiter wakeup order is derived from the recorded effective/base
///   priorities, so priority inversion degrades to bounded waiting rather
///   than unbounded starvation.
/// - Poisoning is tolerated crate-wide: a poisoned guard is recovered via
///   `PoisonError::into_inner`, never propagated to callers.
pub struct Mutex {
    name: String,
    timeout: Duration,
    state: StdMutex<MutexState>,
    condition: Condvar,
    on_boost: Option<BoostCallback>,
}

impl Mutex {
    /// Create a mutex with an explicit timeout supplied by deployment config.
    pub fn new(name: impl Into<String>, timeout: Duration) -> Self {
        Self {
            name: name.into(),
            timeout,
            state: StdMutex::new(MutexState {
                owner: String::new(),
                recursion: 0,
                state: LockState::Free,
                effective_priority: 5.0,
                base_priority: 5.0,
                waiters: Vec::new(),
            }),
            condition: Condvar::new(),
            on_boost: None,
        }
    }

    /// Attach a priority-inheritance callback without changing lock ownership.
    pub fn with_boost_callback(mut self, callback: BoostCallback) -> Self {
        self.on_boost = Some(callback);
        self
    }

    /// Acquire the mutex, preserving Python reentrancy and timeout semantics.
    pub fn acquire(&self, agent_id: &str, priority: f64, blocking: bool) -> WireMap {
        let started = Instant::now();
        let deadline = started + self.timeout;
        let mut state = self.lock_state();

        if state.owner == agent_id && state.recursion > 0 {
            state.recursion += 1;
            return ok([
                ("owner", json!(agent_id)),
                ("recursion", json!(state.recursion)),
            ]);
        }

        if state.state == LockState::Free {
            state.state = LockState::Locked;
            state.owner = agent_id.to_owned();
            state.recursion = 1;
            state.effective_priority = priority;
            state.base_priority = priority;
            return ok([("owner", json!(agent_id))]);
        }

        if priority < state.effective_priority {
            let old = state.effective_priority;
            state.effective_priority = priority;
            if let Some(callback) = &self.on_boost {
                // The callback is advisory and runs while the lock state is
                // held. Contain host/observability failures so a panic cannot
                // poison the synchronization primitive or cross L1.
                let _ = catch_unwind(AssertUnwindSafe(|| {
                    callback(&state.owner, old, priority);
                }));
            }
        }

        if !blocking {
            return fail_with("lock contended", [("owner", json!(state.owner))]);
        }

        state.state = LockState::Contended;
        state.waiters.retain(|waiter| waiter.agent_id != agent_id);
        state.waiters.push(Waiter {
            agent_id: agent_id.to_owned(),
            priority,
        });
        state
            .waiters
            .sort_by(|left, right| left.priority.total_cmp(&right.priority));

        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                drop_waiter(&mut state, agent_id);
                return fail_with(
                    "timeout",
                    [
                        ("owner", json!(state.owner)),
                        ("waited", json!(started.elapsed().as_secs_f64())),
                    ],
                );
            }

            let (next_state, timed_out) = self
                .condition
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next_state;

            if (state.state == LockState::Free || state.owner == agent_id) && !timed_out.timed_out()
            {
                state.state = LockState::Locked;
                state.owner = agent_id.to_owned();
                state.recursion = 1;
                state.effective_priority = priority;
                state.base_priority = priority;
                drop_waiter(&mut state, agent_id);
                return ok([
                    ("owner", json!(agent_id)),
                    ("waited", json!(started.elapsed().as_secs_f64())),
                    ("boosted", json!(started.elapsed().as_secs_f64() > 0.5)),
                ]);
            }

            if timed_out.timed_out() {
                drop_waiter(&mut state, agent_id);
                return fail_with(
                    "timeout",
                    [
                        ("owner", json!(state.owner)),
                        ("waited", json!(started.elapsed().as_secs_f64())),
                    ],
                );
            }
        }
    }

    /// Release one recursion level, enforcing owner identity.
    pub fn release(&self, agent_id: &str) -> WireMap {
        let mut state = self.lock_state();
        if state.owner != agent_id || state.recursion == 0 {
            return fail_with("not the owner", [("owner", json!(state.owner))]);
        }

        state.recursion -= 1;
        if state.recursion > 0 {
            return ok([
                ("owner", json!(agent_id)),
                ("recursion", json!(state.recursion)),
            ]);
        }

        let priority_restored = state.effective_priority != state.base_priority;
        let from = state.effective_priority;
        let to = state.base_priority;
        state.effective_priority = state.base_priority;
        state.state = LockState::Free;
        state.owner.clear();
        self.condition.notify_one();
        ok([
            ("priority_restored", json!(priority_restored)),
            ("from", json!(from)),
            ("to", json!(to)),
        ])
    }

    /// Force-release the mutex for controlled test or shutdown cleanup.
    pub fn force_unlock(&self) -> WireMap {
        let mut state = self.lock_state();
        state.state = LockState::Free;
        state.owner.clear();
        state.recursion = 0;
        state.effective_priority = 5.0;
        state.base_priority = 5.0;
        state.waiters.clear();
        self.condition.notify_all();
        ok([])
    }

    /// Return a stable state snapshot matching Python `Mutex.status()`.
    pub fn status(&self) -> WireMap {
        let state = self.lock_state();
        let waiters: Vec<Value> = state
            .waiters
            .iter()
            .map(|waiter| json!([waiter.agent_id, waiter.priority]))
            .collect();
        BTreeMap::from([
            ("name".to_owned(), json!(self.name)),
            ("state".to_owned(), json!(state.state.as_str())),
            ("owner".to_owned(), json!(state.owner)),
            ("recursion".to_owned(), json!(state.recursion)),
            (
                "effective_priority".to_owned(),
                json!(state.effective_priority),
            ),
            ("base_priority".to_owned(), json!(state.base_priority)),
            ("waiters".to_owned(), json!(waiters)),
            ("waiter_count".to_owned(), json!(state.waiters.len())),
        ])
    }

    fn lock_state(&self) -> MutexGuard<'_, MutexState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[derive(Debug)]
struct SemaphoreState {
    count: usize,
    waiters: Vec<String>,
}

/// Counting semaphore candidate with bounded waiting and waiter cleanup.
pub struct Semaphore {
    name: String,
    max_count: usize,
    timeout: Duration,
    poll_interval: Duration,
    state: StdMutex<SemaphoreState>,
    condition: Condvar,
}

impl Semaphore {
    /// Create a semaphore with explicit deployment timing values.
    pub fn new(
        name: impl Into<String>,
        max_count: usize,
        timeout: Duration,
        poll_interval: Duration,
    ) -> Self {
        Self {
            name: name.into(),
            max_count,
            timeout,
            poll_interval,
            state: StdMutex::new(SemaphoreState {
                count: max_count,
                waiters: Vec::new(),
            }),
            condition: Condvar::new(),
        }
    }

    /// Acquire one permit, returning the remaining count or a structured failure.
    pub fn acquire(&self, agent_id: &str, blocking: bool) -> WireMap {
        let deadline = Instant::now() + self.timeout;
        let mut state = self.lock_state();
        loop {
            if state.count > 0 {
                state.count -= 1;
                remove_waiter(&mut state.waiters, agent_id);
                return ok([("remaining", json!(state.count))]);
            }
            if !blocking {
                return fail_with("no capacity", []);
            }
            if !state.waiters.iter().any(|waiter| waiter == agent_id) {
                state.waiters.push(agent_id.to_owned());
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                remove_waiter(&mut state.waiters, agent_id);
                return fail_with("timeout", []);
            }
            let wait_for = remaining.min(self.poll_interval);
            let (next_state, timed_out) = self
                .condition
                .wait_timeout(state, wait_for)
                .unwrap_or_else(PoisonError::into_inner);
            state = next_state;
            if timed_out.timed_out() && Instant::now() >= deadline {
                remove_waiter(&mut state.waiters, agent_id);
                return fail_with("timeout", []);
            }
        }
    }

    /// Return one permit and wake a queued waiter when capacity allows it.
    pub fn release(&self, _agent_id: &str) -> WireMap {
        let mut state = self.lock_state();
        if state.count < self.max_count {
            state.count += 1;
            if !state.waiters.is_empty() {
                state.waiters.remove(0);
            }
            self.condition.notify_one();
        }
        ok([("remaining", json!(state.count))])
    }

    /// Return the semaphore status snapshot.
    pub fn status(&self) -> WireMap {
        let state = self.lock_state();
        BTreeMap::from([
            ("name".to_owned(), json!(self.name)),
            ("count".to_owned(), json!(state.count)),
            ("max".to_owned(), json!(self.max_count)),
            ("waiters".to_owned(), json!(state.waiters.len())),
        ])
    }

    fn lock_state(&self) -> MutexGuard<'_, SemaphoreState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Drop one agent from a waiter list, preserving order.
fn remove_waiter(waiters: &mut Vec<String>, agent_id: &str) {
    waiters.retain(|waiter| waiter != agent_id);
}

#[derive(Debug)]
struct BarrierState {
    generation: u64,
    arrived: BTreeSet<String>,
}

/// Reusable barrier candidate with timeout cleanup between rounds.
pub struct Barrier {
    name: String,
    count: usize,
    timeout: Duration,
    state: StdMutex<BarrierState>,
    condition: Condvar,
}

impl Barrier {
    /// Create a barrier with explicit participant count and timeout.
    pub fn new(name: impl Into<String>, count: usize, timeout: Duration) -> Self {
        Self {
            name: name.into(),
            count,
            timeout,
            state: StdMutex::new(BarrierState {
                generation: 0,
                arrived: BTreeSet::new(),
            }),
            condition: Condvar::new(),
        }
    }

    /// Arrive at the barrier and return the releaser/waiter role.
    pub fn wait(&self, agent_id: &str) -> WireMap {
        let deadline = Instant::now() + self.timeout;
        let mut state = self.lock_state();
        let generation = state.generation;
        state.arrived.insert(agent_id.to_owned());
        if state.arrived.len() >= self.count {
            let arrived = state.arrived.len();
            state.arrived.clear();
            state.generation = state.generation.wrapping_add(1);
            self.condition.notify_all();
            return ok([("role", json!("releaser")), ("arrived", json!(arrived))]);
        }

        loop {
            if state.generation != generation {
                return ok([
                    ("role", json!("waiter")),
                    ("arrived", json!(state.arrived.len())),
                ]);
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                state.arrived.remove(agent_id);
                return ok([
                    ("role", json!("waiter")),
                    ("arrived", json!(state.arrived.len())),
                ]);
            }
            let (next_state, timed_out) = self
                .condition
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next_state;
            if timed_out.timed_out() && state.generation == generation {
                state.arrived.remove(agent_id);
                return ok([
                    ("role", json!("waiter")),
                    ("arrived", json!(state.arrived.len())),
                ]);
            }
        }
    }

    /// Clear arrivals and start a fresh barrier generation.
    pub fn reset(&self) -> WireMap {
        let mut state = self.lock_state();
        state.arrived.clear();
        state.generation = state.generation.wrapping_add(1);
        self.condition.notify_all();
        ok([])
    }

    /// Return the barrier status snapshot.
    pub fn status(&self) -> WireMap {
        let state = self.lock_state();
        BTreeMap::from([
            ("name".to_owned(), json!(self.name)),
            ("count".to_owned(), json!(self.count)),
            ("arrived".to_owned(), json!(state.arrived.len())),
        ])
    }

    fn lock_state(&self) -> MutexGuard<'_, BarrierState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[derive(Debug)]
struct ConditionState {
    generation: u64,
    waiters: BTreeSet<String>,
    pending_signals: usize,
}

/// Condition-variable candidate with buffered signals and broadcast wakeups.
pub struct Condition {
    name: String,
    timeout: Duration,
    state: StdMutex<ConditionState>,
    condition: Condvar,
}

impl Condition {
    /// Create a condition with an explicit default wait timeout.
    pub fn new(name: impl Into<String>, timeout: Duration) -> Self {
        Self {
            name: name.into(),
            timeout,
            state: StdMutex::new(ConditionState {
                generation: 0,
                waiters: BTreeSet::new(),
                pending_signals: 0,
            }),
            condition: Condvar::new(),
        }
    }

    /// Wait for a signal or the configured timeout.
    pub fn wait(&self, agent_id: &str, timeout: Option<Duration>) -> WireMap {
        let deadline = Instant::now() + timeout.unwrap_or(self.timeout);
        let mut state = self.lock_state();
        if state.pending_signals > 0 {
            state.pending_signals -= 1;
            return ok([("agent_id", json!(agent_id)), ("timed_out", json!(false))]);
        }
        state.waiters.insert(agent_id.to_owned());
        let generation = state.generation;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                state.waiters.remove(agent_id);
                return fail_with(
                    "timeout",
                    [("agent_id", json!(agent_id)), ("timed_out", json!(true))],
                );
            }
            let (next_state, timed_out) = self
                .condition
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next_state;
            if state.generation != generation {
                state.waiters.remove(agent_id);
                return ok([("agent_id", json!(agent_id)), ("timed_out", json!(false))]);
            }
            if timed_out.timed_out() {
                state.waiters.remove(agent_id);
                return fail_with(
                    "timeout",
                    [("agent_id", json!(agent_id)), ("timed_out", json!(true))],
                );
            }
        }
    }

    /// Wake current waiters, or buffer one signal when no waiter exists.
    pub fn signal(&self, agent_id: &str) -> WireMap {
        let mut state = self.lock_state();
        if state.waiters.is_empty() {
            state.pending_signals = state.pending_signals.saturating_add(1);
        } else {
            state.generation = state.generation.wrapping_add(1);
            self.condition.notify_all();
        }
        ok([
            ("signaler", json!(agent_id)),
            ("wakeup", json!(state.waiters.len())),
        ])
    }

    /// Wake all current waiters.
    pub fn broadcast(&self, agent_id: &str) -> WireMap {
        let mut state = self.lock_state();
        state.generation = state.generation.wrapping_add(1);
        let waiters = state.waiters.len();
        self.condition.notify_all();
        ok([("signaler", json!(agent_id)), ("broadcast", json!(waiters))])
    }

    /// Return the condition status snapshot.
    pub fn status(&self) -> WireMap {
        let state = self.lock_state();
        BTreeMap::from([
            ("name".to_owned(), json!(self.name)),
            ("waiters".to_owned(), json!(state.waiters.len())),
        ])
    }

    fn lock_state(&self) -> MutexGuard<'_, ConditionState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[derive(Debug)]
struct RwLockState {
    reader_counts: BTreeMap<String, usize>,
    reader_total: usize,
    writer: Option<String>,
    writer_depth: usize,
    write_waiters: usize,
    writer_queue: VecDeque<u64>,
    next_writer_ticket: u64,
}

/// Read/write lock candidate with writer preference and reentrant reads.
///
/// # Invariants
///
/// - Reads are reentrant per thread; writes stay exclusive behind FIFO
///   writer tickets (`writer_queue`), so queued writers cannot starve.
/// - A timed-out or cancelled writer releases its ticket and wakes its
///   successor — pinned by `kernel_sync_vectors.json`.
pub struct RwLock {
    name: String,
    timeout: Duration,
    poll_interval: Duration,
    state: StdMutex<RwLockState>,
    condition: Condvar,
}

impl RwLock {
    /// Create an RWLock with explicit timeout and polling values.
    pub fn new(name: impl Into<String>, timeout: Duration, poll_interval: Duration) -> Self {
        Self {
            name: name.into(),
            timeout,
            poll_interval,
            state: StdMutex::new(RwLockState {
                reader_counts: BTreeMap::new(),
                reader_total: 0,
                writer: None,
                writer_depth: 0,
                write_waiters: 0,
                writer_queue: VecDeque::new(),
                next_writer_ticket: 0,
            }),
            condition: Condvar::new(),
        }
    }

    /// Acquire a shared read lock with writer-preference semantics.
    pub fn read_lock(&self, agent_id: &str) -> WireMap {
        self.read_lock_with_timeout_and_cancellation(agent_id, self.timeout, None)
    }

    /// Acquire a shared read lock with a per-call timeout override.
    pub fn read_lock_with_timeout(&self, agent_id: &str, timeout: Duration) -> WireMap {
        self.read_lock_with_timeout_and_cancellation(agent_id, timeout, None)
    }

    /// Acquire a shared read lock while observing a cooperative cancellation token.
    pub fn read_lock_with_cancellation(
        &self,
        agent_id: &str,
        cancellation: &CancellationToken,
    ) -> WireMap {
        self.read_lock_with_timeout_and_cancellation(agent_id, self.timeout, Some(cancellation))
    }

    /// Acquire the read lock, honoring timeout and cancellation fail-closed.
    fn read_lock_with_timeout_and_cancellation(
        &self,
        agent_id: &str,
        timeout: Duration,
        cancellation: Option<&CancellationToken>,
    ) -> WireMap {
        if agent_id.is_empty() {
            return fail_with("invalid agent_id", []);
        }
        let deadline = Instant::now() + timeout;
        let mut state = self.lock_state();
        let already_reader = state.reader_counts.get(agent_id).copied().unwrap_or(0) > 0;
        loop {
            if cancellation.is_some_and(|token| token.is_cancelled()) {
                return fail_with("cancelled", []);
            }
            let writer_blocks = state
                .writer
                .as_deref()
                .is_some_and(|writer| writer != agent_id);
            let queued_writer_blocks =
                state.write_waiters > 0 && !already_reader && state.writer.is_none();
            if !writer_blocks && !queued_writer_blocks {
                *state.reader_counts.entry(agent_id.to_owned()).or_insert(0) += 1;
                state.reader_total += 1;
                return ok([
                    ("mode", json!("read")),
                    ("readers", json!(state.reader_total)),
                ]);
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return fail_with("timeout", []);
            }
            let (next_state, timed_out) = self
                .condition
                .wait_timeout(state, remaining.min(self.poll_interval))
                .unwrap_or_else(PoisonError::into_inner);
            state = next_state;
            if timed_out.timed_out() && Instant::now() >= deadline {
                return fail_with("timeout", []);
            }
        }
    }

    /// Acquire an exclusive write lock, tracking queued writers.
    pub fn write_lock(&self, agent_id: &str) -> WireMap {
        self.write_lock_with_optional_cancellation(agent_id, None)
    }

    /// Acquire an exclusive write lock while observing a cooperative cancellation token.
    pub fn write_lock_with_cancellation(
        &self,
        agent_id: &str,
        cancellation: &CancellationToken,
    ) -> WireMap {
        self.write_lock_with_optional_cancellation(agent_id, Some(cancellation))
    }

    /// Acquire the write lock with optional cancellation support.
    fn write_lock_with_optional_cancellation(
        &self,
        agent_id: &str,
        cancellation: Option<&CancellationToken>,
    ) -> WireMap {
        if agent_id.is_empty() {
            return fail_with("invalid agent_id", []);
        }
        let deadline = Instant::now() + self.timeout;
        let mut state = self.lock_state();
        if cancellation.is_some_and(|token| token.is_cancelled()) {
            return fail_with("cancelled", []);
        }
        if state.writer.as_deref() == Some(agent_id) {
            state.writer_depth += 1;
            return ok([
                ("mode", json!("write")),
                ("depth", json!(state.writer_depth)),
            ]);
        }
        if state.reader_total == 0 && state.writer.is_none() && state.writer_queue.is_empty() {
            state.writer = Some(agent_id.to_owned());
            state.writer_depth = 1;
            return ok([
                ("mode", json!("write")),
                ("depth", json!(state.writer_depth)),
            ]);
        }
        let ticket = state.next_writer_ticket;
        state.next_writer_ticket = state.next_writer_ticket.wrapping_add(1);
        state.writer_queue.push_back(ticket);
        state.write_waiters += 1;
        loop {
            if cancellation.is_some_and(|token| token.is_cancelled()) {
                remove_writer_ticket(&mut state, ticket);
                self.condition.notify_all();
                return fail_with("cancelled", []);
            }
            let blocked_by_readers = state.reader_total > 0;
            let blocked_by_writer = state
                .writer
                .as_deref()
                .is_some_and(|writer| writer != agent_id);
            let is_next_writer = state.writer_queue.front() == Some(&ticket);
            if !blocked_by_readers && !blocked_by_writer && is_next_writer {
                state.writer_queue.pop_front();
                state.write_waiters -= 1;
                state.writer = Some(agent_id.to_owned());
                state.writer_depth = 1;
                return ok([
                    ("mode", json!("write")),
                    ("depth", json!(state.writer_depth)),
                ]);
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                remove_writer_ticket(&mut state, ticket);
                self.condition.notify_all();
                return fail_with("timeout", []);
            }
            let (next_state, timed_out) = self
                .condition
                .wait_timeout(state, remaining.min(self.poll_interval))
                .unwrap_or_else(PoisonError::into_inner);
            state = next_state;
            if timed_out.timed_out() && Instant::now() >= deadline {
                remove_writer_ticket(&mut state, ticket);
                self.condition.notify_all();
                return fail_with("timeout", []);
            }
        }
    }

    /// Release the writer or one read hold owned by the agent.
    pub fn unlock(&self, agent_id: &str) -> WireMap {
        if agent_id.is_empty() {
            return fail_with("invalid agent_id", []);
        }
        let mut state = self.lock_state();
        if state.writer.as_deref() == Some(agent_id) {
            state.writer_depth -= 1;
            if state.writer_depth == 0 {
                state.writer = None;
            }
        } else if let Some(count) = state.reader_counts.get_mut(agent_id) {
            *count -= 1;
            let remove_reader = *count == 0;
            state.reader_total -= 1;
            if remove_reader {
                state.reader_counts.remove(agent_id);
            }
        } else {
            return fail_with(
                "not locked",
                [
                    ("writer", json!(state.writer.clone().unwrap_or_default())),
                    ("readers", json!(state.reader_total)),
                ],
            );
        }
        self.condition.notify_all();
        let mut result = ok([
            (
                "mode",
                json!(if state.writer.is_some() {
                    "write"
                } else {
                    "read"
                }),
            ),
            ("readers", json!(state.reader_total)),
        ]);
        if state.writer.is_some() {
            result.insert("depth".to_owned(), json!(state.writer_depth));
        }
        result
    }

    /// Return the RWLock status snapshot.
    pub fn status(&self) -> WireMap {
        let state = self.lock_state();
        BTreeMap::from([
            ("name".to_owned(), json!(self.name)),
            ("readers".to_owned(), json!(state.reader_total)),
            (
                "writer".to_owned(),
                json!(state.writer.clone().unwrap_or_default()),
            ),
            ("writer_depth".to_owned(), json!(state.writer_depth)),
            ("write_waiters".to_owned(), json!(state.write_waiters)),
        ])
    }

    fn lock_state(&self) -> MutexGuard<'_, RwLockState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Drop a mutex waiter and clear the owner when no waiters remain.
fn drop_waiter(state: &mut MutexState, agent_id: &str) {
    state.waiters.retain(|waiter| waiter.agent_id != agent_id);
    if state.owner.is_empty() && state.waiters.is_empty() {
        state.state = LockState::Free;
    }
}

/// Remove one writer ticket from the queue, keeping others ordered.
fn remove_writer_ticket(state: &mut RwLockState, ticket: u64) {
    if let Some(index) = state
        .writer_queue
        .iter()
        .position(|queued| *queued == ticket)
    {
        state.writer_queue.remove(index);
        state.write_waiters = state.write_waiters.saturating_sub(1);
    }
}

/// Build a success wire map from ordered fields.
fn ok<const N: usize>(fields: [(&str, Value); N]) -> WireMap {
    let mut result = BTreeMap::from_iter(
        fields
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value)),
    );
    result.insert("success".to_owned(), json!(true));
    result
}

/// Build a failure wire map with an error label plus ordered fields.
fn fail_with<const N: usize>(error: &str, fields: [(&str, Value); N]) -> WireMap {
    let mut result = BTreeMap::from_iter(
        fields
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value)),
    );
    result.insert("success".to_owned(), json!(false));
    result.insert("error".to_owned(), json!(error));
    result
}
