//! Rust-native cancellation token for bounded kernel waits.

use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

#[derive(Debug, Default)]
struct CancellationState {
    cancelled: bool,
    reason: Option<String>,
}

#[derive(Debug, Default)]
struct CancellationInner {
    state: Mutex<CancellationState>,
    changed: Condvar,
}

/// Cloneable, one-way cancellation signal for kernel-owned waits.
#[derive(Debug, Clone, Default)]
pub struct CancellationToken {
    inner: Arc<CancellationInner>,
}

impl CancellationToken {
    /// Create an active token that has not been cancelled.
    pub fn new() -> Self {
        Self::default()
    }

    /// Cancel this token and retain the first reason.
    ///
    /// Returns `true` only for the transition from active to cancelled. A
    /// repeated cancellation is idempotent and cannot replace the first
    /// reason.
    pub fn cancel(&self, reason: impl Into<String>) -> bool {
        let mut state = self.lock_state();
        if state.cancelled {
            return false;
        }
        state.cancelled = true;
        state.reason = Some(reason.into());
        self.inner.changed.notify_all();
        true
    }

    /// Return whether cancellation has been requested.
    pub fn is_cancelled(&self) -> bool {
        self.lock_state().cancelled
    }

    /// Return the first cancellation reason, if cancellation was requested.
    pub fn reason(&self) -> Option<String> {
        self.lock_state().reason.clone()
    }

    /// Fail a cooperative operation when cancellation has been requested.
    ///
    /// # Errors
    ///
    /// Infallible inspection: returns token state without side effects.
    pub fn check(&self) -> Result<(), CancellationError> {
        let state = self.lock_state();
        if state.cancelled {
            return Err(CancellationError {
                reason: state.reason.clone().unwrap_or_default(),
            });
        }
        Ok(())
    }

    /// Wait for cancellation, returning `false` when the optional timeout elapses.
    pub fn wait(&self, timeout: Option<Duration>) -> bool {
        let deadline = timeout.and_then(|duration| Instant::now().checked_add(duration));
        let mut state = self.lock_state();
        loop {
            if state.cancelled {
                return true;
            }
            let Some(deadline) = deadline else {
                state = self
                    .inner
                    .changed
                    .wait(state)
                    .unwrap_or_else(PoisonError::into_inner);
                continue;
            };
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return false;
            }
            let (next_state, timed_out) = self
                .inner
                .changed
                .wait_timeout(state, remaining)
                .unwrap_or_else(PoisonError::into_inner);
            state = next_state;
            if timed_out.timed_out() && !state.cancelled {
                return false;
            }
        }
    }

    fn lock_state(&self) -> MutexGuard<'_, CancellationState> {
        self.inner
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

/// Error returned when a cooperative operation observes cancellation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CancellationError {
    reason: String,
}

impl CancellationError {
    /// Return the retained cancellation reason.
    pub fn reason(&self) -> &str {
        &self.reason
    }
}

impl Display for CancellationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        if self.reason.is_empty() {
            formatter.write_str("operation cancelled")
        } else {
            write!(formatter, "operation cancelled: {}", self.reason)
        }
    }
}

impl Error for CancellationError {}
