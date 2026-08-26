//! Session lifecycle FSM and record for the host session boundary.
//!
//! Owns the host-session lifecycle graph
//! (Created → Ready → Running ⇄ Paused → Closing → Stopped, with Failed
//! reachable from every state and irreversible) and the per-session record.
//! The record carries a validated identity, an optional live terminal+process
//! binding, and the epoch-seconds creation time. View cursors and the session
//! registry share this record so the FSM, identity, and views stay coherent.

use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::protocol::{ProtocolError, SessionCursor};
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

/// One host session record: identity, lifecycle, binding, and view cursors.
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
    /// Per-session view cursors keyed by view id; views are session-scoped.
    views: BTreeMap<String, SessionCursor>,
}

impl SessionRecord {
    /// Create a record in the `Created` lifecycle at a deterministic timestamp.
    pub fn new(identity: SessionIdentity, created_at: u64) -> Self {
        Self {
            identity,
            lifecycle: SessionLifecycle::Created,
            created_at,
            binding: None,
            views: BTreeMap::new(),
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
    ///
    /// # Errors
    ///
    /// SessionLifecycleError::InvalidTransition when the FSM forbids the move.
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

    /// Attach a view to this session; re-attach re-binds a retained cursor
    /// while preserving its ack cursor.
    pub fn attach_view(&mut self, view_id: impl Into<String>) {
        let view_id = view_id.into();
        let entry = self.views.entry(view_id.clone()).or_insert_with(|| {
            let mut cursor = SessionCursor::new(view_id);
            cursor.attach(self.identity.session_id.clone());
            cursor
        });
        entry.attached = true;
    }

    /// Detach a view while retaining its cursor for later re-attach; returns
    /// whether the view was registered.
    pub fn detach_view(&mut self, view_id: &str) -> bool {
        match self.views.get_mut(view_id) {
            Some(cursor) => {
                cursor.detach();
                true
            }
            None => false,
        }
    }

    /// Advance one view's ack cursor monotonically, never moving it backwards.
    pub fn ack_view(&mut self, view_id: &str, ack_seq: u64) {
        if let Some(cursor) = self.views.get_mut(view_id) {
            cursor.last_acked = cursor
                .last_acked
                .max(i64::try_from(ack_seq).unwrap_or(i64::MAX));
        }
    }

    /// Return a cursor clone for one registered view, attached or detached.
    pub fn view(&self, view_id: &str) -> Option<SessionCursor> {
        self.views.get(view_id).cloned()
    }

    /// Return all view cursors for this session in deterministic view-id order.
    pub fn list_views(&self) -> Vec<SessionCursor> {
        self.views.values().cloned().collect()
    }

    /// Return the number of views registered for this session.
    pub fn view_count(&self) -> usize {
        self.views.len()
    }
}

/// Session container keyed by session id; each record owns its view set.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionRegistry {
    sessions: BTreeMap<String, SessionRecord>,
}

impl Default for SessionRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl SessionRegistry {
    /// Create an empty registry.
    pub fn new() -> Self {
        Self {
            sessions: BTreeMap::new(),
        }
    }

    /// Create and store a session record from a validated identity at the
    /// current epoch time; rejects empty identities and duplicate session ids.
    ///
    /// # Errors
    ///
    /// SessionLifecycleError on duplicate session id or invalid spec.
    pub fn create(&mut self, identity: SessionIdentity) -> Result<(), ProtocolError> {
        self.create_at(identity, now_epoch_secs())
    }

    /// Create and store a session record with a deterministic timestamp.
    pub fn create_at(
        &mut self,
        identity: SessionIdentity,
        created_at: u64,
    ) -> Result<(), ProtocolError> {
        identity.validate()?;
        let session_id = identity.session_id.clone();
        if self.sessions.contains_key(&session_id) {
            return Err(ProtocolError::InvalidContract(format!(
                "duplicate session id: {session_id}"
            )));
        }
        self.sessions
            .insert(session_id, SessionRecord::new(identity, created_at));
        Ok(())
    }

    /// Return an immutable reference to one session record.
    pub fn get(&self, session_id: &str) -> Option<&SessionRecord> {
        self.sessions.get(session_id)
    }

    /// Return a mutable reference for lifecycle or view mutations.
    pub fn get_mut(&mut self, session_id: &str) -> Option<&mut SessionRecord> {
        self.sessions.get_mut(session_id)
    }

    /// Remove a session and return whether it existed.
    pub fn remove(&mut self, session_id: &str) -> bool {
        self.sessions.remove(session_id).is_some()
    }

    /// Return session ids in deterministic order.
    pub fn list_ids(&self) -> Vec<String> {
        self.sessions.keys().cloned().collect()
    }

    /// Return the number of stored sessions.
    pub fn len(&self) -> usize {
        self.sessions.len()
    }

    /// Return whether the registry is empty.
    pub fn is_empty(&self) -> bool {
        self.sessions.is_empty()
    }
}

fn now_epoch_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}
