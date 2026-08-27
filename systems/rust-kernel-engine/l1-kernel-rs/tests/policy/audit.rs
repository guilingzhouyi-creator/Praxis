//! Independent bounded audit-log tests for the Rust kernel.

use std::fs;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use l1_kernel_rs::audit::{AuditEntry, AuditLog, SYSCALL_AUDIT_DETAIL_MAXLEN};
use l1_kernel_rs::persist::EventStore;

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
    let mut wire = serde_json::to_value(&entry).expect("audit entry serializes");
    wire.as_object_mut()
        .expect("audit entry is an object")
        .remove("error");
    let restored: AuditEntry = serde_json::from_value(wire).expect("audit entry parses");
    assert_eq!(restored.error, "");
}

#[test]
fn journal_wiring_persists_audit_rows() {
    let path = path();
    let journal = Arc::new(EventStore::open(&path).expect("journal opens"));
    let log = AuditLog::new();
    log.set_journal(Some(Arc::clone(&journal)));
    log.record_fields("audit.test", "agent", true, "", "detail");
    log.flush().expect("journal flushes");
    let rows = journal
        .query(Some("audit.syscall"), 0, 10)
        .expect("journal query succeeds");
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].payload["op"], "audit.test");
    let _ = fs::remove_file(path);
}
