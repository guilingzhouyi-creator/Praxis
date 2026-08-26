//! Independent integration tests for the Rust-owned durable session store.

use std::fs;
use std::sync::atomic::{AtomicU64, Ordering};

use l1_kernel_rs::session::{SessionBook, SessionSpec, SessionState};
use l1_kernel_rs::session_store::{SESSION_STORE_VERSION, SessionStore};

static TEST_ID: AtomicU64 = AtomicU64::new(1);

fn temp_root(label: &str) -> std::path::PathBuf {
    let id = TEST_ID.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "praxis-rust-session-store-{label}-{}-{id}",
        std::process::id()
    ))
}

fn spec(session_id: &str) -> SessionSpec {
    SessionSpec::new(session_id, "agent-1", "cell-1", "worker", 8)
}

#[test]
fn fresh_store_is_empty_and_writes_versioned_document() {
    let root = temp_root("fresh");
    let mut store = SessionStore::open(&root).expect("open fresh store");
    let book = SessionBook::new(2).expect("book");
    let document = store.save(&book, true).expect("save empty book");
    assert_eq!(document.store_version, SESSION_STORE_VERSION);
    assert_eq!(document.generation, 1);
    assert!(document.clean_shutdown);
    assert!(store.path().is_file());
    assert!(
        SessionStore::open(&root)
            .expect("reopen")
            .document()
            .is_ok()
    );
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn unclean_round_trip_requires_explicit_session_recovery() {
    let root = temp_root("unclean");
    {
        let mut store = SessionStore::open(&root).expect("open");
        let book = SessionBook::new(2).expect("book");
        let session = book.create(spec("session-a")).expect("create");
        session.activate().expect("activate");
        let first = session
            .append_input("input-1", "hello", 1)
            .expect("append input");
        assert_eq!(first.input_seq, 1);
        let document = store.save(&book, false).expect("unclean save");
        assert!(!document.clean_shutdown);
        assert_eq!(document.sessions[0].snapshot.state, SessionState::Crashed);
    }

    let store = SessionStore::open(&root).expect("reopen");
    let book = store.load_book(2).expect("load book");
    let session = book.get("session-a").expect("restored session");
    assert_eq!(session.state(), SessionState::Crashed);
    session.recover().expect("recover");
    session.activate().expect("reactivate");
    let second = session
        .append_input("input-2", "world", 2)
        .expect("append after recovery");
    assert_eq!(second.input_seq, 2);
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn clean_save_rejects_writable_sessions_and_accepts_closed_sessions() {
    let root = temp_root("clean");
    let mut store = SessionStore::open(&root).expect("open");
    let book = SessionBook::new(2).expect("book");
    let session = book.create(spec("session-a")).expect("create");
    session.activate().expect("activate");
    assert!(store.save(&book, true).is_err());
    assert_eq!(store.generation(), 0);
    session.close(true).expect("close");
    let document = store.save(&book, true).expect("clean save");
    assert!(document.clean_shutdown);
    let loaded = store.load_book(2).expect("load");
    assert_eq!(
        loaded.get("session-a").expect("session").state(),
        SessionState::Closed
    );
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn unsupported_document_version_fails_closed() {
    let root = temp_root("version");
    let store = SessionStore::open(&root).expect("open");
    fs::create_dir_all(store.path().parent().expect("parent")).expect("parent");
    fs::write(
        store.path(),
        r#"{"store_version":99,"generation":1,"clean_shutdown":true,"sessions":[]}"#,
    )
    .expect("write invalid document");
    assert!(SessionStore::open(&root).is_err());
    fs::remove_dir_all(root).expect("remove test root");
}

#[test]
fn shared_ts_checkpoint_fixture_round_trips_through_rust_store() {
    let root = temp_root("shared-fixture");
    let store = SessionStore::open(&root).expect("open");
    fs::create_dir_all(store.path().parent().expect("parent")).expect("parent");
    fs::write(
        store.path(),
        include_str!("../../../../tests/fixtures/kernel_session_store_document.json"),
    )
    .expect("write shared fixture");

    let reopened = SessionStore::open(&root).expect("reopen shared fixture");
    let document = reopened.document().expect("read shared fixture");
    assert_eq!(document.store_version, SESSION_STORE_VERSION);
    assert_eq!(document.generation, 7);
    assert!(!document.clean_shutdown);
    assert_eq!(document.sessions.len(), 1);
    assert_eq!(
        document.sessions[0].snapshot.spec.session_id,
        "session-golden"
    );
    assert_eq!(document.sessions[0].snapshot.state, SessionState::Crashed);

    let book = reopened.load_book(2).expect("load shared fixture");
    assert_eq!(
        book.get("session-golden").expect("session").message_count(),
        1
    );
    fs::remove_dir_all(root).expect("remove test root");
}
