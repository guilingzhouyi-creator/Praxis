//! Bounded per-session outbox registry mirroring
//! `ProtocolHost._outboxes` (`src/l2/protocol/host.py`).
//!
//! Each session materializes its replay window lazily on first use and the
//! window is dropped together with the session. The registry is a plain data
//! container; runtime session state and transport stay adapter-owned.

use std::collections::BTreeMap;

use crate::protocol::{Message, Outbox, ProtocolError, OUTBOX_MAXLEN};

/// Bounded per-session replay-window registry.
pub struct OutboxRegistry {
    maxlen: usize,
    outboxes: BTreeMap<String, Outbox>,
}

impl Default for OutboxRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl OutboxRegistry {
    /// Create a registry using the default per-session capacity.
    pub fn new() -> Self {
        Self {
            maxlen: OUTBOX_MAXLEN,
            outboxes: BTreeMap::new(),
        }
    }

    /// Create a registry with a custom positive per-session capacity.
    pub fn with_maxlen(maxlen: usize) -> Result<Self, ProtocolError> {
        if maxlen == 0 {
            return Err(ProtocolError::InvalidContract(
                "maxlen must be a positive integer".to_owned(),
            ));
        }
        Ok(Self {
            maxlen,
            outboxes: BTreeMap::new(),
        })
    }

    /// Return the bounded replay window for a session, creating it lazily.
    pub fn get_or_create(&mut self, session_id: &str) -> &mut Outbox {
        self.outboxes
            .entry(session_id.to_owned())
            .or_insert_with(|| Outbox::new(self.maxlen).expect("registry maxlen is validated"))
    }

    /// Append one outbound message to a session's replay window.
    pub fn append(&mut self, session_id: &str, message: Message) {
        self.get_or_create(session_id).append(message);
    }

    /// Advance a session's ack cursor without dropping buffered messages.
    pub fn ack(&mut self, session_id: &str, seq: u64) {
        self.get_or_create(session_id).ack(seq);
    }

    /// Drop a session's outbox.
    pub fn remove(&mut self, session_id: &str) {
        self.outboxes.remove(session_id);
    }

    /// Session identifiers in stable sorted order.
    pub fn session_ids(&self) -> Vec<String> {
        self.outboxes.keys().cloned().collect()
    }
}