//! Rust candidate for the bounded kernel audit trail.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::to_value;

use crate::persist::EventStore;

/// Maximum in-memory audit rows retained by the default candidate.
pub const SYSCALL_AUDIT_MAX: usize = 5_000;
/// Maximum detail characters retained in one audit row.
pub const SYSCALL_AUDIT_DETAIL_MAXLEN: usize = 200;
/// Default audit query page size.
pub const SYSCALL_AUDIT_QUERY_LIMIT: usize = 100;

/// Immutable audit row crossing the kernel boundary.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AuditEntry {
    /// Operation or syscall name.
    pub op: String,
    /// Calling process or interactive principal.
    pub agent_id: String,
    /// Whether the operation was accepted/successful.
    pub success: bool,
    /// Stable failure text, empty on success.
    #[serde(default)]
    pub error: String,
    /// Bounded operation detail.
    #[serde(default)]
    pub detail: String,
    /// Wall-clock record time in Unix seconds.
    pub timestamp: f64,
}

impl AuditEntry {
    /// Construct an audit row and apply the detail bound.
    pub fn new(
        op: impl Into<String>,
        agent_id: impl Into<String>,
        success: bool,
        error: impl Into<String>,
        detail: impl Into<String>,
    ) -> Self {
        let detail = detail.into();
        Self {
            op: op.into(),
            agent_id: agent_id.into(),
            success,
            error: error.into(),
            detail: detail.chars().take(SYSCALL_AUDIT_DETAIL_MAXLEN).collect(),
            timestamp: unix_timestamp(),
        }
    }
}

struct AuditState {
    entries: VecDeque<AuditEntry>,
    journal: Option<Arc<EventStore>>,
    journal_errors: u64,
}

/// Thread-safe bounded audit trail with optional append-only journal wiring.
pub struct AuditLog {
    max_entries: usize,
    state: Mutex<AuditState>,
}

impl AuditLog {
    /// Create an audit trail with the default row bound.
    pub fn new() -> Self {
        Self::with_capacity(SYSCALL_AUDIT_MAX)
    }

    /// Create an audit trail with an explicit row bound.
    pub fn with_capacity(max_entries: usize) -> Self {
        Self {
            max_entries,
            state: Mutex::new(AuditState {
                entries: VecDeque::with_capacity(max_entries),
                journal: None,
                journal_errors: 0,
            }),
        }
    }

    /// Attach or replace the optional durable event journal.
    pub fn set_journal(&self, journal: Option<Arc<EventStore>>) {
        self.lock_state().journal = journal;
    }

    /// Append one audit row and best-effort persist it as `audit.syscall`.
    pub fn record(&self, entry: AuditEntry) {
        let mut state = self.lock_state();
        if self.max_entries == 0 {
            state.entries.clear();
        } else {
            state.entries.push_back(entry.clone());
            while state.entries.len() > self.max_entries {
                state.entries.pop_front();
            }
        }
        if let Some(journal) = state.journal.as_ref()
            && journal
                .append("audit.syscall", Some(to_value(&entry).unwrap_or_default()))
                .is_err()
        {
            state.journal_errors = state.journal_errors.saturating_add(1);
        }
    }

    /// Record a row from primitive fields.
    pub fn record_fields(
        &self,
        op: impl Into<String>,
        agent_id: impl Into<String>,
        success: bool,
        error: impl Into<String>,
        detail: impl Into<String>,
    ) {
        self.record(AuditEntry::new(op, agent_id, success, error, detail));
    }

    /// Flush the attached journal, if any.
    pub fn flush(&self) -> std::io::Result<()> {
        let journal = self.lock_state().journal.clone();
        if let Some(journal) = journal {
            journal.flush()?;
        }
        Ok(())
    }

    /// Return chronological rows, optionally filtered by caller identity.
    pub fn query(&self, limit: usize, agent_id: Option<&str>) -> Vec<AuditEntry> {
        let state = self.lock_state();
        if limit == 0 {
            return Vec::new();
        }
        if let Some(agent_id) = agent_id {
            let mut rows = state
                .entries
                .iter()
                .rev()
                .filter(|entry| entry.agent_id == agent_id)
                .take(limit)
                .cloned()
                .collect::<Vec<_>>();
            rows.reverse();
            rows
        } else {
            state
                .entries
                .iter()
                .rev()
                .take(limit)
                .cloned()
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect()
        }
    }

    /// Clear the in-memory query ring; durable journal rows are retained.
    pub fn clear(&self) {
        self.lock_state().entries.clear();
    }

    /// Return row count and journal error count for diagnostics.
    pub fn stats(&self) -> (usize, u64) {
        let state = self.lock_state();
        (state.entries.len(), state.journal_errors)
    }

    fn lock_state(&self) -> std::sync::MutexGuard<'_, AuditState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for AuditLog {
    fn default() -> Self {
        Self::new()
    }
}

fn unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

#[cfg(test)]
mod tests {
    use super::{AuditEntry, AuditLog, SYSCALL_AUDIT_DETAIL_MAXLEN};
    use crate::persist::EventStore;
    use std::fs;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_ID: AtomicU64 = AtomicU64::new(1);

    fn path() -> std::path::PathBuf {
        let id = TEST_ID.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!(
            "praxis-rust-audit-{}-{id}.jsonl",
            std::process::id()
        ))
    }

    #[test]
    fn audit_rows_are_bounded_filtered_and_chronological() {
        let log = AuditLog::with_capacity(2);
        log.record_fields("one", "agent-a", true, "", "detail");
        log.record_fields("two", "agent-b", true, "", "detail");
        log.record_fields("three", "agent-a", false, "nope", "detail");
        let all = log.query(100, None);
        assert_eq!(all.len(), 2);
        assert_eq!(all[0].op, "two");
        assert_eq!(log.query(10, Some("agent-a"))[0].op, "three");
    }

    #[test]
    fn detail_is_truncated_and_wire_defaults_are_stable() {
        let detail = "x".repeat(SYSCALL_AUDIT_DETAIL_MAXLEN + 10);
        let entry = AuditEntry::new("op", "agent", false, "error", detail);
        assert_eq!(entry.detail.chars().count(), SYSCALL_AUDIT_DETAIL_MAXLEN);
        let mut wire = serde_json::to_value(&entry).unwrap();
        wire.as_object_mut().unwrap().remove("error");
        let restored: AuditEntry = serde_json::from_value(wire).unwrap();
        assert_eq!(restored.error, "");
    }

    #[test]
    fn journal_wiring_persists_audit_rows() {
        let path = path();
        let journal = Arc::new(EventStore::open(&path).unwrap());
        let log = AuditLog::new();
        log.set_journal(Some(Arc::clone(&journal)));
        log.record_fields("audit.test", "agent", true, "", "detail");
        log.flush().unwrap();
        let rows = journal.query(Some("audit.syscall"), 0, 10).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].payload["op"], "audit.test");
        let _ = fs::remove_file(path);
    }
}
