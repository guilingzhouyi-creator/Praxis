//! Rust-native R1 substrate values for ownership and hot-path metrics.

use std::sync::atomic::{AtomicU64, Ordering};

/// Generation-tagged process handle that prevents stale slot reuse.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ProcessHandle {
    slot: u32,
    generation: u32,
}

impl ProcessHandle {
    /// Construct a handle; generation zero is reserved as an invalid value.
    pub const fn new(slot: u32, generation: u32) -> Option<Self> {
        if generation == 0 {
            return None;
        }
        Some(Self { slot, generation })
    }

    /// Decode the compact internal representation.
    pub const fn from_raw(raw: u64) -> Option<Self> {
        let slot = raw as u32;
        let generation = (raw >> 32) as u32;
        Self::new(slot, generation)
    }

    /// Return the compact representation used by internal queues and maps.
    pub const fn raw(self) -> u64 {
        ((self.generation as u64) << 32) | self.slot as u64
    }

    /// Return the reusable slot index.
    pub const fn slot(self) -> u32 {
        self.slot
    }

    /// Return the generation used to reject stale handles.
    pub const fn generation(self) -> u32 {
        self.generation
    }
}

/// Deterministic ownership partition for process slots.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ShardPlan {
    shard_count: u32,
}

impl ShardPlan {
    /// Create a partition plan; zero shards is rejected rather than panicked.
    pub const fn new(shard_count: u32) -> Result<Self, &'static str> {
        if shard_count == 0 {
            return Err("shard count must be at least one");
        }
        Ok(Self { shard_count })
    }

    /// Return the stable shard for a process handle.
    pub const fn shard_for(self, handle: ProcessHandle) -> u32 {
        handle.slot % self.shard_count
    }

    /// Return the number of ownership partitions.
    pub const fn shard_count(self) -> u32 {
        self.shard_count
    }
}

/// Snapshot of counters that must not require JSON allocation on hot paths.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct QueueMetricSnapshot {
    /// Number of accepted submissions.
    pub submitted: u64,
    /// Number of completed submissions.
    pub completed: u64,
    /// Number of rejected submissions.
    pub rejected: u64,
    /// Current accepted-but-not-completed work.
    pub queue_depth: u64,
    /// Maximum observed queue depth.
    pub peak_queue_depth: u64,
}

/// Lock-free counters for bounded queue admission and completion accounting.
pub struct QueueMetrics {
    submitted: AtomicU64,
    completed: AtomicU64,
    rejected: AtomicU64,
    queue_depth: AtomicU64,
    peak_queue_depth: AtomicU64,
}

impl QueueMetrics {
    /// Create empty counters.
    pub const fn new() -> Self {
        Self {
            submitted: AtomicU64::new(0),
            completed: AtomicU64::new(0),
            rejected: AtomicU64::new(0),
            queue_depth: AtomicU64::new(0),
            peak_queue_depth: AtomicU64::new(0),
        }
    }

    /// Record one admission decision without touching queue storage.
    pub fn record_submit(&self, accepted: bool) {
        if !accepted {
            self.rejected.fetch_add(1, Ordering::Relaxed);
            return;
        }
        self.submitted.fetch_add(1, Ordering::Relaxed);
        let depth = self.queue_depth.fetch_add(1, Ordering::Relaxed) + 1;
        let mut peak = self.peak_queue_depth.load(Ordering::Relaxed);
        while depth > peak {
            match self.peak_queue_depth.compare_exchange_weak(
                peak,
                depth,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(observed) => peak = observed,
            }
        }
    }

    /// Record completion and saturate depth at zero on duplicate completion.
    pub fn record_complete(&self) {
        self.record_complete_batch(1);
    }

    /// Record multiple completions with one counter update and one depth CAS.
    pub fn record_complete_batch(&self, count: u64) {
        if count == 0 {
            return;
        }
        self.completed.fetch_add(count, Ordering::Relaxed);
        let mut depth = self.queue_depth.load(Ordering::Relaxed);
        while depth != 0 {
            let next = depth.saturating_sub(count);
            match self.queue_depth.compare_exchange_weak(
                depth,
                next,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => return,
                Err(observed) => depth = observed,
            }
        }
    }

    /// Read a compact counter snapshot for metrics or benchmark reporting.
    pub fn snapshot(&self) -> QueueMetricSnapshot {
        QueueMetricSnapshot {
            submitted: self.submitted.load(Ordering::Relaxed),
            completed: self.completed.load(Ordering::Relaxed),
            rejected: self.rejected.load(Ordering::Relaxed),
            queue_depth: self.queue_depth.load(Ordering::Relaxed),
            peak_queue_depth: self.peak_queue_depth.load(Ordering::Relaxed),
        }
    }
}

impl Default for QueueMetrics {
    /// Create zeroed queue metrics.
    fn default() -> Self {
        Self::new()
    }
}
