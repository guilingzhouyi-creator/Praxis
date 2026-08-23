//! Session identity triple separation for the host session boundary.
//!
//! Mirrors `src/l2/protocol/records.py` `SessionIdentity`. The three required
//! identity concerns are deliberately distinct (P0.1 three-way separation): a
//! terminal may host multiple sessions, while one session owns exactly one
//! terminal+process binding. Optional identity fields default to empty and
//! only the required fields are enforced fail-closed.

use serde::{Deserialize, Serialize};

use crate::protocol::ProtocolError;
use crate::session::SESSION_MAX_ID_BYTES;

/// Versioned TS-neutral session identity with three-way separation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionIdentity {
    /// Stable session identifier; unique across the host.
    pub session_id: String,
    /// Hosting terminal identifier; one terminal may host many sessions.
    pub terminal_id: String,
    /// Binding process identifier; the terminal+process binding is session-owned.
    pub process_id: String,
    /// Owning user identifier; empty when unbound.
    #[serde(default)]
    pub user_id: String,
    /// Session role selected by the upper-layer dispatcher; empty when unbound.
    #[serde(default)]
    pub role: String,
    /// Owning Cell identifier; empty when unbound.
    #[serde(default)]
    pub cell_id: String,
    /// Memory scope selector; empty when unbound.
    #[serde(default)]
    pub memory_scope: String,
}

impl SessionIdentity {
    /// Build an identity from the three required concerns; rejects empty
    /// required fields or over-long values fail-closed.
    pub fn new(
        session_id: impl Into<String>,
        terminal_id: impl Into<String>,
        process_id: impl Into<String>,
    ) -> Result<Self, ProtocolError> {
        let identity = Self {
            session_id: session_id.into(),
            terminal_id: terminal_id.into(),
            process_id: process_id.into(),
            user_id: String::new(),
            role: String::new(),
            cell_id: String::new(),
            memory_scope: String::new(),
        };
        identity.validate()?;
        Ok(identity)
    }

    /// Set the optional identity fields and return the identity for chaining.
    pub fn with_optional(
        mut self,
        user_id: impl Into<String>,
        role: impl Into<String>,
        cell_id: impl Into<String>,
        memory_scope: impl Into<String>,
    ) -> Self {
        self.user_id = user_id.into();
        self.role = role.into();
        self.cell_id = cell_id.into();
        self.memory_scope = memory_scope.into();
        self
    }

    /// Validate required fields are non-empty and every field fits the budget.
    pub fn validate(&self) -> Result<(), ProtocolError> {
        for (name, value) in [
            ("session_id", self.session_id.as_str()),
            ("terminal_id", self.terminal_id.as_str()),
            ("process_id", self.process_id.as_str()),
        ] {
            if value.is_empty() {
                return Err(ProtocolError::InvalidContract(format!(
                    "{name} must be a non-empty string"
                )));
            }
        }
        for (name, value) in [
            ("session_id", self.session_id.as_str()),
            ("terminal_id", self.terminal_id.as_str()),
            ("process_id", self.process_id.as_str()),
            ("user_id", self.user_id.as_str()),
            ("role", self.role.as_str()),
            ("cell_id", self.cell_id.as_str()),
            ("memory_scope", self.memory_scope.as_str()),
        ] {
            if value.len() > SESSION_MAX_ID_BYTES {
                return Err(ProtocolError::InvalidContract(format!(
                    "{name} exceeds {SESSION_MAX_ID_BYTES} bytes"
                )));
            }
        }
        Ok(())
    }
}