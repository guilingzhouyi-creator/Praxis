//! Independent append-only journal mechanism tests for the Rust kernel.

use l1_kernel_rs::persist::{EventStore, PERSIST_QUERY_LIMIT};
use serde_json::json;
use std::fs;
use std::sync::atomic::{AtomicU64, Ordering};

static TEST_ID: AtomicU64 = AtomicU64::new(1);

fn temp_path(label: &str) -> std::path::PathBuf {
    let id = TEST_ID.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "praxis-rust-{label}-{}-{id}.jsonl",
        std::process::id()
    ))
}

fn cleanup(path: &std::path::Path) {
    let _ = fs::remove_file(path);
}

#[test]
fn append_query_count_and_last_seq_preserve_python_shape() {
    let path = temp_path("journal");
    let store = EventStore::with_commit_batch(&path, 2).expect("journal");
    assert_eq!(store.last_seq().expect("seq"), 0);
    assert_eq!(
        store
            .append("alpha", Some(json!({"v": 1})))
            .expect("append"),
        1
    );
    assert_eq!(
        store.append("beta", Some(json!({"v": 2}))).expect("append"),
        2
    );
    assert_eq!(
        store
            .append("alpha", Some(json!({"v": 3})))
            .expect("append"),
        3
    );
    assert_eq!(store.count(None).expect("count"), 3);
    assert_eq!(store.count(Some("alpha")).expect("count"), 2);
    let rows = store
        .query(Some("alpha"), 1, PERSIST_QUERY_LIMIT)
        .expect("query");
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].payload, json!({"v": 3}));
    assert_eq!(store.last_seq().expect("seq"), 3);
    cleanup(&path);
}

#[test]
fn append_many_is_sequenced_and_empty_payload_is_an_object() {
    let path = temp_path("batch");
    let store = EventStore::open(&path).expect("journal");
    let empty = store
        .append_many(std::iter::empty::<(String, serde_json::Value)>())
        .expect("empty batch");
    assert!(empty.is_empty());
    let seqs = store
        .append_many([
            ("one".to_owned(), json!({"x": 1})),
            ("two".to_owned(), json!({"x": 2})),
        ])
        .expect("batch");
    assert_eq!(seqs, vec![1, 2]);
    assert_eq!(store.append("empty", None).expect("empty payload"), 3);
    assert_eq!(
        store.query(None, 0, 10).expect("query")[2].payload,
        json!({})
    );
    cleanup(&path);
}

#[test]
fn records_survive_reopen_and_sequence_gaps_fail_closed() {
    let path = temp_path("reopen");
    {
        let store = EventStore::open(&path).expect("journal");
        store
            .append("persisted", Some(json!({"ok": true})))
            .expect("append");
        store.flush().expect("flush");
    }
    let reopened = EventStore::open(&path).expect("reopen");
    assert_eq!(reopened.last_seq().expect("seq"), 1);
    assert_eq!(
        reopened.query(None, 0, 10).expect("query")[0].event,
        "persisted"
    );
    fs::write(
        &path,
        "{\"seq\":2,\"event\":\"gap\",\"payload\":{},\"ts\":0}\n",
    )
    .expect("corrupt journal");
    assert!(EventStore::open(&path).is_err());
    cleanup(&path);
}
