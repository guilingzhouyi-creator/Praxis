//! Rust-native bounded notification buffer candidate.

use std::collections::VecDeque;
use std::sync::{Mutex, PoisonError};

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// One supervisory notification with caller-supplied time.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Notification {
    /// Topic consumed by an external notification adapter.
    pub topic: String,
    /// Structured payload kept outside the protected execution path.
    pub payload: Value,
    /// Explicit timestamp; the candidate does not read a system clock.
    #[serde(rename = "ts")]
    pub timestamp: f64,
}

/// Compact notification-buffer counters.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct NotificationStats {
    /// Number of notifications currently retained.
    pub queued: usize,
    /// Number of oldest notifications evicted at capacity.
    pub dropped: u64,
}

/// Thread-safe bounded notification queue with newest-first reads.
pub struct NotificationBuffer {
    capacity: usize,
    entries: Mutex<VecDeque<Notification>>,
    dropped: Mutex<u64>,
}

impl NotificationBuffer {
    /// Create an empty buffer; zero capacity is rejected rather than lossy.
    ///
    /// # Errors
    ///
    /// Err when retention capacity is zero.
    pub fn new(capacity: usize) -> Result<Self, &'static str> {
        if capacity == 0 {
            return Err("notification capacity must be positive");
        }
        Ok(Self {
            capacity,
            entries: Mutex::new(VecDeque::with_capacity(capacity)),
            dropped: Mutex::new(0),
        })
    }

    /// Publish a notification and evict the oldest item at capacity.
    pub fn publish(
        &self,
        topic: impl Into<String>,
        payload: Value,
        timestamp: f64,
    ) -> Result<(), &'static str> {
        if !timestamp.is_finite() {
            return Err("notification timestamp must be finite");
        }
        let mut entries = self.entries.lock().unwrap_or_else(PoisonError::into_inner);
        if entries.len() == self.capacity {
            entries.pop_front();
            *self.dropped.lock().unwrap_or_else(PoisonError::into_inner) += 1;
        }
        entries.push_back(Notification {
            topic: topic.into(),
            payload,
            timestamp,
        });
        Ok(())
    }

    /// Return retained notifications newest first; zero means no limit.
    pub fn recent(&self, limit: usize) -> Vec<Notification> {
        let entries = self.entries.lock().unwrap_or_else(PoisonError::into_inner);
        let count = if limit == 0 {
            entries.len()
        } else {
            limit.min(entries.len())
        };
        entries.iter().rev().take(count).cloned().collect()
    }

    /// Return current queue and drop counters.
    pub fn stats(&self) -> NotificationStats {
        NotificationStats {
            queued: self
                .entries
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .len(),
            dropped: *self.dropped.lock().unwrap_or_else(PoisonError::into_inner),
        }
    }

    /// Remove retained notifications while preserving cumulative drop count.
    pub fn clear(&self) {
        self.entries
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clear();
    }

    /// Reset retained notifications and cumulative drop count.
    pub fn reset(&self) {
        self.clear();
        *self.dropped.lock().unwrap_or_else(PoisonError::into_inner) = 0;
    }
}

impl Default for NotificationBuffer {
    fn default() -> Self {
        Self::new(64).expect("default notification capacity is valid")
    }
}
