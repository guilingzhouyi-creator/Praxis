//! Bounded per-session outbox registry and per-view ack cursors mirroring
//! `ProtocolHost._outboxes` (`src/l2/protocol/host.py`) together with the
//! `SessionManager` view multiplexer (`packages/protocol-ts`).
//!
//! Each session materializes its replay window lazily on first use and the
//! window is dropped together with the session. Views attach to a session
//! with their own monotonic ack cursors; a view's ack never erases another
//! view's replay window. The registry is a plain data container; runtime
//! session state and transport stay adapter-owned.

use std::collections::btree_map::Entry;
use std::collections::BTreeMap;

use crate::protocol::{Message, Outbox, ProtocolError, SessionCursor, OUTBOX_MAXLEN};

/// Bounded per-session replay-window registry.
pub struct OutboxRegistry {
    maxlen: usize,
    outboxes: BTreeMap<String, Outbox>,
    views: BTreeMap<(String, String), SessionCursor>,
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
            views: BTreeMap::new(),
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
            views: BTreeMap::new(),
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

    /// Drop a session's outbox together with any views bound to it.
    pub fn remove(&mut self, session_id: &str) {
        self.outboxes.remove(session_id);
        self.views.retain(|(sid, _), _| sid != session_id);
    }

    /// Session identifiers in stable sorted order.
    pub fn session_ids(&self) -> Vec<String> {
        self.outboxes.keys().cloned().collect()
    }

    /// Attach a view to a session (idempotent; re-attach rebinds the cursor).
    pub fn attach(&mut self, session_id: &str, view_id: &str) {
        let key = (session_id.to_owned(), view_id.to_owned());
        match self.views.entry(key) {
            Entry::Occupied(mut entry) => {
                entry.get_mut().attach(session_id);
            }
            Entry::Vacant(entry) => {
                let mut cursor = SessionCursor::new(view_id);
                cursor.attach(session_id);
                entry.insert(cursor);
            }
        }
    }

    /// Detach a view while retaining its cursor for a later re-attach.
    pub fn detach(&mut self, session_id: &str, view_id: &str) {
        if let Some(cursor) = self.views.get_mut(&(session_id.to_owned(), view_id.to_owned())) {
            cursor.detach();
        }
    }

    /// Advance one view's ack cursor monotonically. The view's ack never
    /// touches the session outbox or any other view's cursor (non-destructive
    /// invariant, mirroring `SessionMultiplexer.ack`); unknown views are a
    /// no-op.
    pub fn ack_view(&mut self, session_id: &str, view_id: &str, seq: u64) {
        if let Some(cursor) = self.views.get_mut(&(session_id.to_owned(), view_id.to_owned())) {
            cursor.last_acked = cursor
                .last_acked
                .max(i64::try_from(seq).unwrap_or(i64::MAX));
        }
    }

    /// Return one view's retained cursor, if any.
    pub fn cursor(&self, session_id: &str, view_id: &str) -> Option<&SessionCursor> {
        self.views.get(&(session_id.to_owned(), view_id.to_owned()))
    }

    /// Replay a view's window over its session outbox strictly after
    /// `after_seq`, starting from the view's own ack cursor (a view without a
    /// cursor replays from `-1`).
    pub fn replay(&self, session_id: &str, view_id: &str, after_seq: i64) -> Vec<Message> {
        let last_acked = self
            .cursor(session_id, view_id)
            .map_or(-1, |cursor| cursor.last_acked);
        match self.outboxes.get(session_id) {
            Some(outbox) => outbox
                .unacked_after(last_acked)
                .into_iter()
                .filter(|message| i64::try_from(message.seq).unwrap_or(i64::MAX) > after_seq)
                .collect(),
            None => Vec::new(),
        }
    }

    /// Shared watermark for a session: the lagging attached view's cursor,
    /// or -1 when no view is attached (mirrors `SessionMultiplexer.watermark`).
    pub fn watermark(&self, session_id: &str) -> i64 {
        let mut lowest = i64::MAX;
        for ((sid, _), cursor) in &self.views {
            if sid == session_id && cursor.attached {
                lowest = lowest.min(cursor.last_acked);
            }
        }
        if lowest == i64::MAX { -1 } else { lowest }
    }
}