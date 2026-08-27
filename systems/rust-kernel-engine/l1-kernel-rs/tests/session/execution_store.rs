//! Independent integration coverage for the combined Rust execution checkpoint.

use std::fs;
use std::sync::atomic::{AtomicU64, Ordering};

use l1_kernel_rs::agent_loop::{AgentLoopBook, AgentLoopSpec, AgentLoopState};
use l1_kernel_rs::execution_store::{EXECUTION_STORE_VERSION, ExecutionStore, ExecutionStoreError};
use l1_kernel_rs::session::{SessionBook, SessionSpec, SessionState};
use l1_kernel_rs::substrate::ProcessHandle;
use l1_kernel_rs::terminal::{TerminalBook, TerminalSpec, TerminalState};

static TEST_ID: AtomicU64 = AtomicU64::new(1);

fn temp_root(label: &str) -> std::path::PathBuf {
    let id = TEST_ID.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "praxis-rust-execution-store-{label}-{}-{id}",
        std::process::id()
    ))
}

fn build_books() -> (SessionBook, TerminalBook, AgentLoopBook) {
    let sessions = SessionBook::new(2).expect("session book");
    let terminals = TerminalBook::new();
    let loops = AgentLoopBook::new();
    let session = sessions
        .create(SessionSpec::new(
            "session-a",
            "agent-a",
            "cell-a",
            "worker",
            8,
        ))
        .expect("session");
    session.activate().expect("activate");
    terminals
        .register(TerminalSpec::new("terminal-a", 8, 8))
        .expect("terminal");
    terminals.attach("terminal-a", "session-a").expect("attach");
    loops
        .register(AgentLoopSpec::new(
            "loop-a",
            "agent-a",
            "cell-a",
            "session-a",
            "terminal-a",
        ))
        .expect("loop");
    (sessions, terminals, loops)
}

#[test]
fn clean_checkpoint_round_trip_preserves_sorted_books() {
    let root = temp_root("clean");
    let (sessions, terminals, loops) = build_books();
    sessions
        .get("session-a")
        .expect("session")
        .close(true)
        .expect("close");
    let mut store = ExecutionStore::open(&root).expect("open");
    let document = store
        .save(&sessions, &terminals, &loops, true)
        .expect("clean save");
    assert_eq!(document.store_version, EXECUTION_STORE_VERSION);
    assert_eq!(document.generation, 1);
    assert!(document.clean_shutdown);
    let restored = store.load_state(2).expect("load");
    assert_eq!(
        restored.sessions.get("session-a").expect("session").state(),
        SessionState::Closed
    );
    assert_eq!(
        restored
            .terminals
            .snapshot("terminal-a")
            .expect("terminal")
            .state,
        TerminalState::Created
    );
    assert_eq!(
        restored.loops.snapshot("loop-a").expect("loop").state,
        AgentLoopState::Created
    );
    if root.exists() {
        fs::remove_dir_all(root).expect("remove root");
    }
}

#[test]
fn unclean_checkpoint_never_restores_live_process_or_active_loop() {
    let root = temp_root("unclean");
    let (sessions, terminals, loops) = build_books();
    terminals
        .bind_process_handle(
            "terminal-a",
            ProcessHandle::from_raw((1_u64 << 32) | 41).expect("handle"),
        )
        .expect("bind");
    terminals.start("terminal-a").expect("start");
    loops
        .attach(
            "loop-a",
            sessions.get("session-a").expect("session").as_ref(),
            &terminals,
        )
        .expect("attach loop");
    loops.start("loop-a").expect("start loop");
    let mut store = ExecutionStore::open(&root).expect("open");
    let document = store
        .save(&sessions, &terminals, &loops, false)
        .expect("unclean save");
    assert!(!document.clean_shutdown);
    assert_eq!(document.terminals[0].state, TerminalState::Created);
    assert_eq!(document.terminals[0].process_id, None);
    assert_eq!(document.loops[0].state, AgentLoopState::Failed);
    let restored = store.load_state(2).expect("load");
    assert_eq!(
        restored.sessions.get("session-a").expect("session").state(),
        SessionState::Crashed
    );
    assert_eq!(
        restored
            .terminals
            .snapshot("terminal-a")
            .expect("terminal")
            .state,
        TerminalState::Created
    );
    assert_eq!(
        restored.loops.snapshot("loop-a").expect("loop").state,
        AgentLoopState::Failed
    );
    fs::remove_dir_all(root).expect("remove root");
}

#[test]
fn clean_checkpoint_rejects_writable_or_live_state() {
    let root = temp_root("reject");
    let (sessions, terminals, loops) = build_books();
    let mut store = ExecutionStore::open(&root).expect("open");
    assert!(matches!(
        store.save(&sessions, &terminals, &loops, true),
        Err(ExecutionStoreError::WritableSession(_))
    ));
    sessions
        .get("session-a")
        .expect("session")
        .close(true)
        .expect("close");
    terminals
        .bind_process_handle(
            "terminal-a",
            ProcessHandle::from_raw((1_u64 << 32) | 42).expect("handle"),
        )
        .expect("bind");
    assert!(matches!(
        store.save(&sessions, &terminals, &loops, true),
        Err(ExecutionStoreError::LiveProcessBinding(_))
    ));
    if root.exists() {
        fs::remove_dir_all(root).expect("remove root");
    }
}

#[test]
fn unsupported_store_version_fails_closed() {
    let root = temp_root("version");
    let store = ExecutionStore::open(&root).expect("open");
    fs::create_dir_all(store.path().parent().expect("parent")).expect("parent");
    fs::write(
        store.path(),
        r#"{"store_version":99,"generation":1,"clean_shutdown":true,"sessions":[],"terminals":[],"loops":[]}"#,
    )
    .expect("write document");
    assert!(ExecutionStore::open(&root).is_err());
    fs::remove_dir_all(root).expect("remove root");
}

#[test]
fn shared_execution_fixture_round_trips_through_rust_store() {
    let root = temp_root("shared-fixture");
    let store = ExecutionStore::open(&root).expect("open");
    fs::create_dir_all(store.path().parent().expect("parent")).expect("parent");
    fs::write(
        store.path(),
        include_str!("../../../../../tests/fixtures/kernel_execution_store_document.json"),
    )
    .expect("write shared fixture");

    let reopened = ExecutionStore::open(&root).expect("reopen shared fixture");
    let document = reopened.document().expect("read shared fixture");
    assert_eq!(document.store_version, EXECUTION_STORE_VERSION);
    assert_eq!(document.generation, 3);
    assert!(!document.clean_shutdown);
    assert_eq!(document.sessions.len(), 1);
    assert_eq!(document.terminals.len(), 1);
    assert_eq!(document.loops.len(), 1);
    assert_eq!(
        document.sessions[0].snapshot.spec.session_id,
        "session-golden"
    );
    assert_eq!(document.terminals[0].terminal_id, "terminal-golden");
    assert_eq!(document.loops[0].spec.loop_id, "loop-golden");

    let restored = reopened.load_state(2).expect("load shared fixture");
    assert_eq!(
        restored
            .sessions
            .get("session-golden")
            .expect("session")
            .state(),
        SessionState::Crashed
    );
    assert_eq!(
        restored
            .terminals
            .snapshot("terminal-golden")
            .expect("terminal")
            .state,
        TerminalState::Created
    );
    assert_eq!(
        restored.loops.snapshot("loop-golden").expect("loop").state,
        AgentLoopState::Failed
    );
    fs::remove_dir_all(root).expect("remove root");
}
