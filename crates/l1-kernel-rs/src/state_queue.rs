//! Rust-native sharded state and bounded work-queue prototype for R1.

use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use crate::substrate::{ProcessHandle, QueueMetricSnapshot, QueueMetrics, ShardPlan};

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
pub struct ShardedStateStore {
    plan: ShardPlan,
    shards: Vec<Mutex<StateShard>>,
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

/// Bounded FIFO queue using shared atomic admission metrics.
pub struct BoundedWorkQueue {
    capacity: usize,
    items: Mutex<VecDeque<WorkItem>>,
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
        items.push_back(item);
        self.metrics.record_submit(true);
        true
    }

    /// Remove the oldest item; completion is recorded separately after work runs.
    pub fn try_pop(&self) -> Option<WorkItem> {
        self.lock_items().pop_front()
    }

    /// Mark a popped item complete and reduce in-flight metric depth.
    pub fn record_complete(&self) {
        self.metrics.record_complete();
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

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::{BoundedWorkQueue, ShardedStateStore, TaskState, WorkItem};
    use crate::substrate::{ProcessHandle, QueueMetrics};

    fn handle(slot: u32, generation: u32) -> ProcessHandle {
        ProcessHandle::new(slot, generation).expect("valid handle")
    }

    #[test]
    fn sharded_store_rejects_stale_generations_and_tracks_transitions() {
        let store = ShardedStateStore::new(2).expect("valid store");
        let current = handle(3, 1);
        let stale = handle(3, 2);
        assert_eq!(store.shard_for(current), 1);
        store.insert(current, TaskState::Ready).expect("insert");
        assert!(store.insert(stale, TaskState::Ready).is_err());
        let running = store
            .transition(current, TaskState::Ready, TaskState::Running)
            .expect("ready to running");
        assert_eq!(running.transition_seq, 1);
        assert_eq!(running.state, TaskState::Running);
        assert!(
            store
                .transition(stale, TaskState::Running, TaskState::Ready)
                .is_err()
        );
        assert_eq!(store.len(), 1);
    }

    #[test]
    fn stopped_state_is_terminal_until_explicit_resume() {
        let store = ShardedStateStore::new(1).expect("valid store");
        let process = handle(1, 1);
        store.insert(process, TaskState::Ready).expect("insert");
        store
            .transition(process, TaskState::Ready, TaskState::Stopped)
            .expect("stop");
        assert!(
            store
                .transition(process, TaskState::Stopped, TaskState::Running)
                .is_err()
        );
        store
            .transition(process, TaskState::Stopped, TaskState::Ready)
            .expect("resume to ready");
        assert_eq!(store.get(process).expect("record").state, TaskState::Ready);
    }

    #[test]
    fn bounded_queue_rejects_at_capacity_and_reports_completion() {
        let metrics = Arc::new(QueueMetrics::new());
        let queue = BoundedWorkQueue::new(1, Arc::clone(&metrics)).expect("valid queue");
        let process = handle(2, 1);
        assert!(queue.try_push(WorkItem {
            handle: process,
            sequence: 1,
        }));
        assert!(!queue.try_push(WorkItem {
            handle: process,
            sequence: 2,
        }));
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.try_pop().expect("item").sequence, 1);
        queue.record_complete();
        assert!(queue.is_empty());
        let snapshot = queue.metrics();
        assert_eq!(snapshot.submitted, 1);
        assert_eq!(snapshot.rejected, 1);
        assert_eq!(snapshot.queue_depth, 0);
        assert_eq!(snapshot.peak_queue_depth, 1);
    }

    #[test]
    fn empty_state_and_zero_capacity_are_explicit() {
        let store = ShardedStateStore::new(1).expect("valid store");
        assert!(store.is_empty());
        assert!(BoundedWorkQueue::new(0, Arc::new(QueueMetrics::new())).is_err());
    }

    #[test]
    fn sharded_state_survives_parallel_insert_and_transitions() {
        use std::thread;

        let store = Arc::new(ShardedStateStore::new(4).expect("valid store"));
        let workers = (0..4)
            .map(|worker| {
                let store = Arc::clone(&store);
                thread::spawn(move || {
                    for offset in 0..16 {
                        let process = handle(worker * 16 + offset, 1);
                        store.insert(process, TaskState::Ready).expect("insert");
                        store
                            .transition(process, TaskState::Ready, TaskState::Running)
                            .expect("run");
                        store
                            .transition(process, TaskState::Running, TaskState::Ready)
                            .expect("yield");
                    }
                })
            })
            .collect::<Vec<_>>();
        for worker in workers {
            worker.join().expect("state worker joins");
        }
        assert_eq!(store.len(), 64);
    }
}
