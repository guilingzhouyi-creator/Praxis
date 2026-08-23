//! Session lifecycle FSM and record for the host session boundary.
//!
//! Owns the host-session lifecycle graph
//! (Created → Ready → Running ⇄ Paused → Closing → Stopped, with Failed
//! reachable from every state and irreversible) and the per-session record.
//! The record carries a validated identity, an optional live terminal+process
//! binding, and the epoch-seconds creation time. View cursors and the session
//! registry share this record so the FSM, identity, and views stay coherent.

use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::protocol::ProtocolError;
use crate::session::SESSION_MAX_ID_BYTES;
use crate::session_identity::SessionIdentity;

/// Host session lifecycle independent of the session mechanism's session state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionLifecycle {
    /// Identity exists but the session is not yet ready to run.
    Created,
    /// The session is initialized and ready to accept work.
    Ready,
    /// The session is actively executing.
    Running,
    /// Execution is suspended and can resume.
    Paused,
    /// Shutdown has begun and no new work is accepted.
    Closing,
    /// The session stopped cleanly and cannot be reopened.
    Stopped,
    /// The session failed; this state is terminal and irreversible.
    Failed,
}

impl SessionLifecycle {
    /// Return the stable wire spelling of this state.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Ready => "ready",
            Self::Running => "running",
            Self::Paused => "paused",
            Self::Closing => "closing",
            Self::Stopped => "stopped",
            Self::Failed => "failed",
        }
    }

    fn can_transition_to(self, target: Self) -> bool {
        matches!(
            (self, target),
            (Self::Created, Self::Ready | Self::Failed)
                | (Self::Ready, Self::Running | Self::Failed)
                | (Self::Running, Self::Paused | Self::Closing | Self::Failed)
                | (Self::Paused, Self::Running | Self::Failed)
                | (Self::Closing, Self::Stopped | Self::Failed)
                | (Self::Stopped, Self::Failed)
        )
    }
}

/// Live terminal+process binding for one host session.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionBinding {
    /// Hosting terminal identifier.
    pub terminal_id: String,
    /// Binding process identifier.
    pub process_id: String,
}

impl SessionBinding {
    /// Build a binding; rejects empty or over-long identifiers fail-closed.
    pub fn new(
        terminal_id: impl Into<String>,
        process_id: impl Into<String>,
    ) -> Result<Self, ProtocolError> {
        let binding = Self {
            terminal_id: terminal_id.into(),
            process_id: process_id.into(),
        };
        binding.validate()?;
        Ok(binding)
    }

    fn validate(&self) -> Result<(), ProtocolError> {
        for (name, value) in [
            ("terminal_id", self.terminal_id.as_str()),
            ("process_id", self.process_id.as_str()),
        ] {
            if value.is_empty() {
                return Err(ProtocolError::InvalidContract(format!(
                    "{name} must be a non-empty string"
                )));
            }
            if value.len() > SESSION_MAX_ID_BYTES {
                return Err(ProtocolError::InvalidContract(format!(
                    "{name} exceeds {SESSION_MAX_ID_BYTES} bytes"
                )));
            }
        }
        Ok(())
    }
}

/// One host session record: identity, lifecycle, and optional live binding.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionRecord {
    /// Session identity (three-way separation).
    pub identity: SessionIdentity,
    /// Current lifecycle state.
    pub lifecycle: SessionLifecycle,
    /// Epoch-seconds creation timestamp.
    pub created_at: u64,
    /// Live terminal+process binding, absent until bound.
    pub binding: Option<SessionBinding>,
}

impl SessionRecord {
    /// Create a record in the `Created` lifecycle at a deterministic timestamp.
    pub fn new(identity: SessionIdentity, created_at: u64) -> Self {
        Self {
            identity,
            lifecycle: SessionLifecycle::Created,
            created_at,
            binding: None,
        }
    }

    /// Create a record in the `Created` lifecycle at the current epoch time.
    pub fn now(identity: SessionIdentity) -> Self {
        Self::new(identity, now_epoch_secs())
    }

    /// Return the current lifecycle state.
    pub const fn state(&self) -> SessionLifecycle {
        self.lifecycle
    }

    /// Return whether a transition would be accepted without mutating state.
    pub fn can_transition(&self, target: SessionLifecycle) -> bool {
        self.lifecycle.can_transition_to(target)
    }

    /// Validate and apply one lifecycle transition; state is unchanged on error.
    pub fn transition(&mut self, next: SessionLifecycle) -> Result<(), ProtocolError> {
        if !self.lifecycle.can_transition_to(next) {
            return Err(ProtocolError::InvalidContract(format!(
                "invalid session lifecycle transition: {} -> {}",
                self.lifecycle.as_str(),
                next.as_str(),
            )));
        }
        self.lifecycle = next;
        Ok(())
    }

    /// Bind the session to a live terminal+process pairing.
    pub fn bind(&mut self, binding: SessionBinding) {
        self.binding = Some(binding);
    }

    /// Clear the live terminal+process binding.
    pub fn unbind(&mut self) {
        self.binding = None;
    }
}

fn now_epoch_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}