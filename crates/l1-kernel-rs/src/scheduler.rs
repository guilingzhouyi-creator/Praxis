//! Rust-native scheduler candidate joining process state and bounded work.

use std::sync::Arc;

use crate::state_queue::{
    BoundedWorkQueue, ProcessHandleAllocator, ShardedStateStore, StateRecord, TaskState, WorkItem,
};
use crate::substrate::{ProcessHandle, QueueMetricSnapshot, QueueMetrics};

/// Deployment limits for the scheduler candidate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SchedulerConfig {
    /// Maximum number of reusable process slots.
    pub max_processes: u32,
    /// Number of independent state ownership shards.
    pub shard_count: u32,
    /// Maximum number of queued work items.
    pub queue_capacity: usize,
}

impl SchedulerConfig {
    /// Build explicit scheduler limits.
    pub const fn new(max_processes: u32, shard_count: u32, queue_capacity: usize) -> Self {
        Self {
            max_processes,
            shard_count,
            queue_capacity,
        }
    }
}

/// Fail-closed scheduler boundary errors.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SchedulerError {
    /// The process-slot or state capacity cannot accept another process.
    CapacityExhausted,
    /// The queue cannot accept another work item.
    QueueFull,
    /// The supplied handle is absent or from an old generation.
    InvalidHandle,
    /// The requested state transition is not valid for this operation.
    InvalidState,
    /// The process is still running and cannot be reaped.
    NotReapable,
}

/// Candidate scheduler with explicit process, queue, and handle ownership.
pub struct KernelScheduler {
    handles: ProcessHandleAllocator,
    state: ShardedStateStore,
    queue: BoundedWorkQueue,
}

impl KernelScheduler {
    /// Create a scheduler candidate without starting worker threads.
    pub fn new(config: SchedulerConfig) -> Result<Self, &'static str> {
        let handles = ProcessHandleAllocator::new(config.max_processes)?;
        let state = ShardedStateStore::new(config.shard_count)?;
        let metrics = Arc::new(QueueMetrics::new());
        let queue = BoundedWorkQueue::new(config.queue_capacity, metrics)?;
        Ok(Self {
            handles,
            state,
            queue,
        })
    }

    /// Allocate a process slot in READY state.
    pub fn spawn(&self) -> Result<ProcessHandle, SchedulerError> {
        let handle = self
            .handles
            .allocate()
            .map_err(|_| SchedulerError::CapacityExhausted)?;
        if self.state.insert(handle, TaskState::Ready).is_err() {
            let _ = self.handles.release(handle);
            return Err(SchedulerError::CapacityExhausted);
        }
        Ok(handle)
    }

    /// Move a READY process to RUNNING and enqueue one typed work item.
    pub fn schedule(&self, handle: ProcessHandle, sequence: u64) -> Result<(), SchedulerError> {
        self.state
            .transition(handle, TaskState::Ready, TaskState::Running)
            .map_err(|_| SchedulerError::InvalidState)?;
        if self.queue.try_push(WorkItem { handle, sequence }) {
            Ok(())
        } else {
            let _ = self
                .state
                .transition(handle, TaskState::Running, TaskState::Ready);
            Err(SchedulerError::QueueFull)
        }
    }

    /// Move a READY process directly to RUNNING for an already-owned worker.
    ///
    /// This avoids enqueue/dequeue churn when an execution host has its own
    /// bounded WorkerPool. Queue metrics remain untouched because no scheduler
    /// queue item was admitted.
    pub fn dispatch_direct(&self, handle: ProcessHandle) -> Result<(), SchedulerError> {
        self.state
            .transition(handle, TaskState::Ready, TaskState::Running)
            .map(|_| ())
            .map_err(|_| SchedulerError::InvalidState)
    }

    /// Claim the oldest valid RUNNING item, dropping stale or stopped work.
    pub fn claim_next(&self) -> Option<WorkItem> {
        while let Some(item) = self.queue.try_pop() {
            if self
                .state
                .get(item.handle)
                .is_some_and(|record| record.state == TaskState::Running)
            {
                return Some(item);
            }
            self.queue.record_complete();
        }
        None
    }

    /// Complete a claimed item and return its process to READY.
    pub fn complete(&self, handle: ProcessHandle) -> Result<(), SchedulerError> {
        self.state
            .transition(handle, TaskState::Running, TaskState::Ready)
            .map_err(|_| SchedulerError::InvalidState)?;
        self.queue.record_complete();
        Ok(())
    }

    /// Complete a directly dispatched process without touching queue metrics.
    pub fn complete_direct(&self, handle: ProcessHandle) -> Result<(), SchedulerError> {
        self.state
            .transition(handle, TaskState::Running, TaskState::Ready)
            .map(|_| ())
            .map_err(|_| SchedulerError::InvalidState)
    }

    /// Stop a READY or RUNNING process; queued work is discarded on claim.
    pub fn stop(&self, handle: ProcessHandle) -> Result<(), SchedulerError> {
        if self
            .state
            .transition(handle, TaskState::Ready, TaskState::Stopped)
            .is_ok()
            || self
                .state
                .transition(handle, TaskState::Running, TaskState::Stopped)
                .is_ok()
        {
            Ok(())
        } else if self.state.get(handle).is_none() {
            Err(SchedulerError::InvalidHandle)
        } else {
            Err(SchedulerError::InvalidState)
        }
    }

    /// Stop work that has already been claimed by a runtime worker.
    pub fn stop_claimed(&self, handle: ProcessHandle) -> Result<(), SchedulerError> {
        self.state
            .transition(handle, TaskState::Running, TaskState::Stopped)
            .map_err(|_| SchedulerError::InvalidState)?;
        self.queue.record_complete();
        Ok(())
    }

    /// Stop a directly dispatched process without decrementing queue metrics.
    pub fn stop_direct(&self, handle: ProcessHandle) -> Result<(), SchedulerError> {
        self.state
            .transition(handle, TaskState::Running, TaskState::Stopped)
            .map(|_| ())
            .map_err(|_| SchedulerError::InvalidState)
    }

    /// Reap a non-running process and release its generation-tagged slot.
    pub fn reap(&self, handle: ProcessHandle) -> Result<(), SchedulerError> {
        let record = self
            .state
            .get(handle)
            .ok_or(SchedulerError::InvalidHandle)?;
        if record.state == TaskState::Running {
            return Err(SchedulerError::NotReapable);
        }
        self.state
            .remove(handle)
            .map_err(|_| SchedulerError::InvalidHandle)?;
        self.handles
            .release(handle)
            .map_err(|_| SchedulerError::InvalidHandle)
    }

    /// Read a process state without exposing ownership locks.
    pub fn state(&self, handle: ProcessHandle) -> Option<StateRecord> {
        self.state.get(handle)
    }

    /// Return queue accounting for fixed-work evidence.
    pub fn queue_metrics(&self) -> QueueMetricSnapshot {
        self.queue.metrics()
    }
}
