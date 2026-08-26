//! Rust-native sharded state and bounded work-queue prototype for R1.

use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

use crate::cancellation::CancellationToken;
use crate::substrate::{ProcessHandle, QueueMetricSnapshot, QueueMetrics, ShardPlan};

/// Poll interval used while a worker waits for queue work or cancellation.
pub const WORK_QUEUE_CANCELLATION_POLL_INTERVAL: Duration = Duration::from_millis(5);

/// Rust-native lifecycle state for a scheduled process slot.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaskState {
    /// Ready to receive work.
    Ready,
    /// Currently executing work.
    Running,
    /// Waiting for an external dependency.
    Blocked,
    /// Cancelled and unable to execute until explicitly resumed.
    Stopped,
    /// Terminated and awaiting removal.
    Zombie,
}

impl TaskState {
    fn can_transition(self, next: Self) -> bool {
        matches!(
            (self, next),
            (Self::Ready, Self::Running | Self::Stopped | Self::Zombie)
                | (
                    Self::Running,
                    Self::Ready | Self::Blocked | Self::Stopped | Self::Zombie
                )
                | (Self::Blocked, Self::Ready | Self::Stopped | Self::Zombie)
                | (Self::Stopped, Self::Ready)
        )
    }
}

/// A cloned state record returned without exposing shard locks.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StateRecord {
    /// Stable generation-tagged process handle.
    pub handle: ProcessHandle,
    /// Current lifecycle state.
    pub state: TaskState,
    /// Monotonic transition count within this slot generation.
    pub transition_seq: u64,
}

#[derive(Debug)]
struct StateShard {
    slots: HashMap<u32, StateRecord>,
}

/// Sharded process state store with no global table lock on normal operations.
///
/// # Invariants
///
/// - Each shard carries its own lock; normal admission never crosses a
///   global table lock.
/// - Slot reuse is generation-guarded: a stale handle fails closed instead
///   of resolving to a recycled record.
pub struct ShardedStateStore {
    plan: ShardPlan,
    shards: Vec<Mutex<StateShard>>,
}

#[derive(Debug, Clone, Copy)]
struct HandleSlot {
    generation: u32,
    occupied: bool,
}

#[derive(Debug, Default)]
struct HandleAllocatorState {
    slots: Vec<HandleSlot>,
    free_slots: VecDeque<u32>,
    next_slot: u32,
    active: u32,
}

/// Bounded Rust-owned process-slot allocator with generation-safe reuse.
pub struct ProcessHandleAllocator {
    max_slots: u32,
    state: Mutex<HandleAllocatorState>,
}

impl ProcessHandleAllocator {
    /// Create an allocator with an explicit maximum slot count.
    pub fn new(max_slots: u32) -> Result<Self, &'static str> {
        if max_slots == 0 {
            return Err("process handle capacity must be positive");
        }
        Ok(Self {
            max_slots,
            state: Mutex::new(HandleAllocatorState::default()),
        })
    }

    /// Allocate a fresh handle or a released slot with its next generation.
    pub fn allocate(&self) -> Result<ProcessHandle, &'static str> {
        let mut state = self.lock_state();
        if let Some(slot) = state.free_slots.pop_front() {
            let record = state
                .slots
                .get_mut(slot as usize)
                .ok_or("free process slot is missing")?;
            if record.occupied {
                return Err("free process slot is occupied");
            }
            record.occupied = true;
            let generation = record.generation;
            state.active = state.active.saturating_add(1);
            return ProcessHandle::new(slot, generation).ok_or("invalid process generation");
        }
        if state.next_slot >= self.max_slots {
            return Err("process handle capacity exhausted");
        }
        let slot = state.next_slot;
        state.next_slot = state.next_slot.saturating_add(1);
        state.slots.push(HandleSlot {
            generation: 1,
            occupied: true,
        });
        state.active = state.active.saturating_add(1);
        ProcessHandle::new(slot, 1).ok_or("invalid process generation")
    }

    /// Release a current handle and advance its generation before reuse.
    pub fn release(&self, handle: ProcessHandle) -> Result<(), &'static str> {
        let mut state = self.lock_state();
        let record = state
            .slots
            .get_mut(handle.slot() as usize)
            .ok_or("process handle slot is missing")?;
        if !record.occupied || record.generation != handle.generation() {
            return Err("process handle generation is stale");
        }
        let next_generation = record
            .generation
            .checked_add(1)
            .ok_or("process handle generation exhausted")?;
        record.generation = next_generation;
        record.occupied = false;
        state.active = state.active.saturating_sub(1);
        state.free_slots.push_back(handle.slot());
        Ok(())
    }

    /// Return whether a handle is currently allocated at its exact generation.
    pub fn is_current(&self, handle: ProcessHandle) -> bool {
        let state = self.lock_state();
        state
            .slots
            .get(handle.slot() as usize)
            .is_some_and(|record| record.occupied && record.generation == handle.generation())
    }

    /// Return the number of currently allocated handles.
    pub fn active_count(&self) -> u32 {
        self.lock_state().active
    }

    fn lock_state(&self) -> MutexGuard<'_, HandleAllocatorState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl ShardedStateStore {
    /// Create a store with one independent mutex per ownership shard.
    pub fn new(shard_count: u32) -> Result<Self, &'static str> {
        let plan = ShardPlan::new(shard_count)?;
        let shards = (0..shard_count)
            .map(|_| {
                Mutex::new(StateShard {
                    slots: HashMap::new(),
                })
            })
            .collect();
        Ok(Self { plan, shards })
    }

    /// Return the stable shard selected for a process handle.
    pub fn shard_for(&self, handle: ProcessHandle) -> u32 {
        self.plan.shard_for(handle)
    }

    /// Insert a new generation in an unused slot.
    pub fn insert(&self, handle: ProcessHandle, state: TaskState) -> Result<(), &'static str> {
        let mut shard = self.lock_shard(handle);
        if let Some(existing) = shard.slots.get(&handle.slot()) {
            return if existing.handle == handle {
                Err("process handle already exists")
            } else {
                Err("process slot is occupied by another generation")
            };
        }
        shard.slots.insert(
            handle.slot(),
            StateRecord {
                handle,
                state,
                transition_seq: 0,
            },
        );
        Ok(())
    }

    /// Return a copy only when the generation exactly matches.
    pub fn get(&self, handle: ProcessHandle) -> Option<StateRecord> {
        let shard = self.lock_shard(handle);
        shard
            .slots
            .get(&handle.slot())
            .copied()
            .filter(|record| record.handle == handle)
    }

    /// Apply one validated lifecycle transition under the owning shard lock.
    pub fn transition(
        &self,
        handle: ProcessHandle,
        expected: TaskState,
        next: TaskState,
    ) -> Result<StateRecord, &'static str> {
        let mut shard = self.lock_shard(handle);
        let record = shard
            .slots
            .get_mut(&handle.slot())
            .ok_or("process handle is missing")?;
        if record.handle != handle {
            return Err("process handle generation is stale");
        }
        if record.state != expected {
            return Err("process state does not match transition precondition");
        }
        if !record.state.can_transition(next) {
            return Err("process lifecycle transition is not allowed");
        }
        record.state = next;
        record.transition_seq = record.transition_seq.saturating_add(1);
        Ok(*record)
    }

    /// Remove a process only when its generation exactly matches.
    pub fn remove(&self, handle: ProcessHandle) -> Result<StateRecord, &'static str> {
        let mut shard = self.lock_shard(handle);
        let record = shard
            .slots
            .get(&handle.slot())
            .copied()
            .ok_or("process handle is missing")?;
        if record.handle != handle {
            return Err("process handle generation is stale");
        }
        shard.slots.remove(&handle.slot());
        Ok(record)
    }

    /// Count all records; intended for snapshots, not a hot-path operation.
    pub fn len(&self) -> usize {
        self.shards
            .iter()
            .map(|shard| self.lock_mutex(shard).slots.len())
            .sum()
    }

    /// Return whether the store has no records.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    fn lock_shard(&self, handle: ProcessHandle) -> MutexGuard<'_, StateShard> {
        let shard = &self.shards[self.shard_for(handle) as usize];
        self.lock_mutex(shard)
    }

    fn lock_mutex<'a>(&self, shard: &'a Mutex<StateShard>) -> MutexGuard<'a, StateShard> {
        shard.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Typed unit of work that can cross a bounded queue without JSON allocation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkItem {
    /// Process that owns this work.
    pub handle: ProcessHandle,
    /// Caller-provided sequence for idempotence and audit correlation.
    pub sequence: u64,
}

/// Reasons a cancellable queue wait can stop without returning work.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueueWaitError {
    /// The caller's cancellation token was set before work was claimed.
    Cancelled,
}

/// Bounded FIFO queue using shared atomic admission metrics.
///
/// # Invariants
///
/// - Capacity is hard-bounded: admission beyond capacity fails fast instead
///   of blocking the caller.
/// - Pops are token-aware — a caller whose cancellation token is already set
///   receives `QueueWaitError::Cancelled` before any work executes.
/// - Completion accounting is atomic (single CAS depth update), so repeated
///   completions cannot underflow the fixed-work totals.
pub struct BoundedWorkQueue {
    capacity: usize,
    items: Mutex<VecDeque<WorkItem>>,
    not_empty: Condvar,
    not_full: Condvar,
    metrics: Arc<QueueMetrics>,
}

impl BoundedWorkQueue {
    /// Create a queue with caller-owned metrics; zero capacity is rejected.
    pub fn new(capacity: usize, metrics: Arc<QueueMetrics>) -> Result<Self, &'static str> {
        if capacity == 0 {
            return Err("queue capacity must be positive");
        }
        Ok(Self {
            capacity,
            items: Mutex::new(VecDeque::with_capacity(capacity)),
            not_empty: Condvar::new(),
            not_full: Condvar::new(),
            metrics,
        })
    }

    /// Admit one item or reject it immediately when capacity is exhausted.
    pub fn try_push(&self, item: WorkItem) -> bool {
        let mut items = self.lock_items();
        if items.len() == self.capacity {
            self.metrics.record_submit(false);
            return false;
        }
        self.metrics.record_submit(true);
        items.push_back(item);
        self.not_empty.notify_one();
        true
    }

    /// Admit one item, sleeping on backpressure instead of spinning.
    pub fn push_wait(&self, item: WorkItem) {
        let mut items = self.lock_items();
        while items.len() == self.capacity {
            items = self
                .not_full
                .wait(items)
                .unwrap_or_else(PoisonError::into_inner);
        }
        self.metrics.record_submit(true);
        items.push_back(item);
        self.not_empty.notify_one();
    }

    /// Remove the oldest item; completion is recorded separately after work runs.
    pub fn try_pop(&self) -> Option<WorkItem> {
        let mut items = self.lock_items();
        let item = items.pop_front();
        if item.is_some() {
            self.not_full.notify_one();
        }
        item
    }

    /// Drain up to `limit` items under one lock acquisition.
    pub fn drain_batch(&self, limit: usize, output: &mut Vec<WorkItem>) -> usize {
        if limit == 0 {
            return 0;
        }
        let mut items = self.lock_items();
        let available = limit.min(items.len());
        output.extend(items.drain(..available));
        if available > 0 {
            self.not_full.notify_all();
        }
        available
    }

    /// Remove the oldest item, sleeping until a producer supplies one.
    pub fn pop_wait(&self) -> WorkItem {
        let mut items = self.lock_items();
        while items.is_empty() {
            items = self
                .not_empty
                .wait(items)
                .unwrap_or_else(PoisonError::into_inner);
        }
        let item = items.pop_front().expect("queue wait guarantees an item");
        self.not_full.notify_one();
        item
    }

    /// Remove the oldest item, or stop waiting when cancellation is observed.
    pub fn pop_wait_with_cancellation(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<WorkItem, QueueWaitError> {
        let mut items = self.lock_items();
        loop {
            if cancellation.is_cancelled() {
                return Err(QueueWaitError::Cancelled);
            }
            if let Some(item) = items.pop_front() {
                self.not_full.notify_one();
                return Ok(item);
            }
            let (next_items, _) = self
                .not_empty
                .wait_timeout(items, WORK_QUEUE_CANCELLATION_POLL_INTERVAL)
                .unwrap_or_else(PoisonError::into_inner);
            items = next_items;
        }
    }

    /// Mark a popped item complete and reduce in-flight metric depth.
    pub fn record_complete(&self) {
        self.metrics.record_complete();
    }

    /// Mark a drained batch complete with one metrics update.
    pub fn record_complete_batch(&self, count: usize) {
        self.metrics.record_complete_batch(count as u64);
    }

    /// Return the current number of queued items.
    pub fn len(&self) -> usize {
        self.lock_items().len()
    }

    /// Return whether no item is currently queued.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Read the queue's shared admission/completion metrics.
    pub fn metrics(&self) -> QueueMetricSnapshot {
        self.metrics.snapshot()
    }

    fn lock_items(&self) -> MutexGuard<'_, VecDeque<WorkItem>> {
        self.items.lock().unwrap_or_else(PoisonError::into_inner)
    }
}
