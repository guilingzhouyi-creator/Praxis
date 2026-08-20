//! Rust fixed-capacity channel candidate behind the ChannelPort contract.

use std::collections::VecDeque;
use std::sync::{Condvar, Mutex as StdMutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use serde_json::Value;

/// JSON-only ring channel; interpreter objects never cross the port boundary.
pub struct RingChannel {
    capacity: usize,
    overwrite: bool,
    state: StdMutex<ChannelState>,
    not_full: Condvar,
    not_empty: Condvar,
}

#[derive(Debug)]
struct ChannelState {
    buffer: VecDeque<Value>,
    closed: bool,
}

impl RingChannel {
    /// Create a fixed-capacity channel; capacity zero is rejected explicitly.
    pub fn new(capacity: usize, overwrite: bool) -> Result<Self, &'static str> {
        if capacity == 0 {
            return Err("capacity must be at least one");
        }
        Ok(Self {
            capacity,
            overwrite,
            state: StdMutex::new(ChannelState {
                buffer: VecDeque::with_capacity(capacity),
                closed: false,
            }),
            not_full: Condvar::new(),
            not_empty: Condvar::new(),
        })
    }

    /// Enqueue a JSON item, returning false on timeout or closure.
    pub fn put(&self, item: Value, timeout: Option<Duration>) -> bool {
        let deadline = timeout.map(|duration| Instant::now() + duration);
        let mut state = self.lock_state();
        if state.closed {
            return false;
        }
        if self.overwrite && state.buffer.len() == self.capacity {
            state.buffer.pop_front();
        }
        while state.buffer.len() == self.capacity && !state.closed {
            let Some(deadline) = deadline else {
                state = self
                    .not_full
                    .wait(state)
                    .unwrap_or_else(PoisonError::into_inner);
                continue;
            };
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return false;
            }
            let (next, timed_out) = self
                .not_full
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next;
            if timed_out.timed_out() && state.buffer.len() == self.capacity {
                return false;
            }
        }
        if state.closed {
            return false;
        }
        state.buffer.push_back(item);
        self.not_empty.notify_one();
        true
    }

    /// Dequeue the oldest item, returning None on timeout or closed-empty state.
    pub fn get(&self, timeout: Option<Duration>) -> Option<Value> {
        let deadline = timeout.map(|duration| Instant::now() + duration);
        let mut state = self.lock_state();
        while state.buffer.is_empty() && !state.closed {
            let Some(deadline) = deadline else {
                state = self
                    .not_empty
                    .wait(state)
                    .unwrap_or_else(PoisonError::into_inner);
                continue;
            };
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return None;
            }
            let (next, timed_out) = self
                .not_empty
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next;
            if timed_out.timed_out() && state.buffer.is_empty() {
                return None;
            }
        }
        let item = state.buffer.pop_front();
        if item.is_some() {
            self.not_full.notify_one();
        }
        item
    }

    /// Return the oldest item without removing it.
    pub fn peek(&self, timeout: Option<Duration>) -> Option<Value> {
        let deadline = timeout.map(|duration| Instant::now() + duration);
        let mut state = self.lock_state();
        while state.buffer.is_empty() && !state.closed {
            let Some(deadline) = deadline else {
                state = self
                    .not_empty
                    .wait(state)
                    .unwrap_or_else(PoisonError::into_inner);
                continue;
            };
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return None;
            }
            let (next, timed_out) = self
                .not_empty
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next;
            if timed_out.timed_out() && state.buffer.is_empty() {
                return None;
            }
        }
        state.buffer.front().cloned()
    }

    /// Return the number of queued items.
    pub fn size(&self) -> usize {
        self.lock_state().buffer.len()
    }

    /// Return the fixed maximum number of queued items.
    pub const fn capacity(&self) -> usize {
        self.capacity
    }

    /// Close the channel and wake blocked producers and consumers.
    pub fn close(&self) {
        let mut state = self.lock_state();
        state.closed = true;
        self.not_empty.notify_all();
        self.not_full.notify_all();
    }

    /// Remove and return every currently queued item in FIFO order.
    pub fn drain(&self) -> Vec<Value> {
        let mut state = self.lock_state();
        let items: Vec<Value> = state.buffer.drain(..).collect();
        self.not_full.notify_all();
        items
    }

    /// Return the fraction of capacity currently in use.
    pub fn utilization(&self) -> f64 {
        self.size() as f64 / self.capacity as f64
    }

    /// Return true once the channel has been closed.
    pub fn is_closed(&self) -> bool {
        self.lock_state().closed
    }

    fn lock_state(&self) -> MutexGuard<'_, ChannelState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[cfg(test)]
mod tests {
    use super::RingChannel;
    use serde_json::json;
    use std::sync::Arc;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn fifo_put_get_peek_and_drain_preserve_json_values() {
        let channel = RingChannel::new(4, false).unwrap();
        assert!(channel.put(json!("a"), Some(Duration::from_millis(10))));
        assert!(channel.put(json!({"n": 2}), Some(Duration::from_millis(10))));
        assert_eq!(
            channel.peek(Some(Duration::from_millis(10))),
            Some(json!("a"))
        );
        assert_eq!(
            channel.get(Some(Duration::from_millis(10))),
            Some(json!("a"))
        );
        assert_eq!(channel.drain(), vec![json!({"n": 2})]);
        assert_eq!(channel.size(), 0);
    }

    #[test]
    fn bounded_put_times_out_and_overwrite_discards_oldest() {
        let channel = RingChannel::new(1, false).unwrap();
        assert!(channel.put(json!(1), None));
        assert!(!channel.put(json!(2), Some(Duration::from_millis(5))));

        let overwrite = RingChannel::new(2, true).unwrap();
        assert!(overwrite.put(json!("a"), None));
        assert!(overwrite.put(json!("b"), None));
        assert!(overwrite.put(json!("c"), None));
        assert_eq!(overwrite.get(None), Some(json!("b")));
        assert_eq!(overwrite.get(None), Some(json!("c")));
    }

    #[test]
    fn close_unblocks_waiters_and_rejects_future_puts() {
        let channel = Arc::new(RingChannel::new(1, false).unwrap());
        let waiting = Arc::clone(&channel);
        let join = thread::spawn(move || waiting.get(None));
        thread::sleep(Duration::from_millis(5));
        channel.close();
        assert_eq!(join.join().unwrap(), None);
        assert!(!channel.put(json!("closed"), None));
        assert!(channel.is_closed());
    }

    #[test]
    fn invalid_capacity_and_utilization_are_explicit() {
        assert!(RingChannel::new(0, false).is_err());
        let channel = RingChannel::new(4, false).unwrap();
        assert_eq!(channel.utilization(), 0.0);
        channel.put(json!(1), None);
        assert_eq!(channel.utilization(), 0.25);
    }
}
