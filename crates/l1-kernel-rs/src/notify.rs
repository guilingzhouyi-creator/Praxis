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

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::NotificationBuffer;

    #[test]
    fn buffer_is_bounded_and_reads_newest_first() {
        let buffer = NotificationBuffer::new(2).expect("valid buffer");
        buffer
            .publish("first", json!({"n": 1}), 1.0)
            .expect("publish");
        buffer
            .publish("second", json!({"n": 2}), 2.0)
            .expect("publish");
        buffer
            .publish("third", json!({"n": 3}), 3.0)
            .expect("publish");
        let recent = buffer.recent(0);
        assert_eq!(recent[0].topic, "third");
        assert_eq!(recent[1].topic, "second");
        assert_eq!(buffer.stats().dropped, 1);
    }

    #[test]
    fn limits_and_reset_are_explicit() {
        let buffer = NotificationBuffer::new(2).expect("valid buffer");
        buffer.publish("a", json!(null), 1.0).expect("publish");
        buffer.publish("b", json!(null), 2.0).expect("publish");
        assert_eq!(buffer.recent(1).len(), 1);
        buffer.clear();
        assert_eq!(buffer.stats().queued, 0);
        assert_eq!(buffer.stats().dropped, 0);
        buffer.publish("c", json!(null), 3.0).expect("publish");
        buffer.publish("d", json!(null), 4.0).expect("publish");
        buffer.publish("e", json!(null), 5.0).expect("publish");
        buffer.reset();
        assert_eq!(buffer.stats().queued, 0);
        assert_eq!(buffer.stats().dropped, 0);
    }

    #[test]
    fn invalid_capacity_and_timestamp_fail_closed() {
        assert!(NotificationBuffer::new(0).is_err());
        let buffer = NotificationBuffer::default();
        assert!(buffer.publish("bad", json!(null), f64::NAN).is_err());
    }
}
