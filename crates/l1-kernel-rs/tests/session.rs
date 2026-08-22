//! Independent integration coverage for the Rust session truth boundary.

use std::sync::Arc;
use std::thread;

use l1_kernel_rs::session::{
    MessageRole, SESSION_CHECKPOINT_VERSION, SESSION_CONTRACT_VERSION, Session, SessionBook,
    SessionError, SessionInput, SessionSpec, SessionState,
};

fn spec(id: &str, max_messages: usize) -> SessionSpec {
    SessionSpec::new(id, "agent-1", "cell-1", "operator", max_messages)
}

#[test]
fn input_sequence_and_cursor_pages_are_authoritative_and_fifo() {
    let session = Session::new(spec("session-seq", 8)).expect("valid session");
    assert_eq!(session.state(), SessionState::Created);
    assert_eq!(
        session.append_input("m-0", "before active", 1),
        Err(SessionError::NotWritable(SessionState::Created))
    );
    session.activate().expect("activate");

    let first = session
        .append_input("m-1", "hello", 10)
        .expect("first input");
    assert_eq!(first.sequence, 1);
    assert_eq!(first.input_seq, 1);
    let event = session
        .append_event("m-2", 1, MessageRole::Assistant, "hi", 11)
        .expect("assistant event");
    assert_eq!(event.sequence, 2);
    assert_eq!(event.input_seq, 1);
    let second = session
        .append_input("m-3", "next", 12)
        .expect("second input");
    assert_eq!(second.input_seq, 2);
    assert_eq!(
        session.append_event("m-bad", 99, MessageRole::Tool, "bad", 13),
        Err(SessionError::UnknownInputSequence(99))
    );

    let first_page = session.messages_page(None, 2).expect("first page");
    assert_eq!(first_page.items.len(), 2);
    assert_eq!(first_page.total, 3);
    assert_eq!(first_page.next_cursor, Some(2));
    let second_page = session
        .messages_page(first_page.next_cursor, 2)
        .expect("second page");
    assert_eq!(second_page.items.len(), 1);
    assert_eq!(second_page.items[0].sequence, 3);
    assert_eq!(second_page.next_cursor, None);
}

#[test]
fn lifecycle_and_recovery_require_explicit_transitions() {
    let session = Session::new(spec("session-life", 8)).expect("valid session");
    assert_eq!(
        session.close(true),
        Err(SessionError::InvalidTransition {
            from: SessionState::Created,
            to: SessionState::Closed,
        })
    );
    session.activate().expect("activate");
    session.append_input("m-1", "work", 1).expect("input");
    session.close(false).expect("crash marker");
    assert_eq!(session.state(), SessionState::Crashed);
    assert_eq!(
        session.append_input("m-2", "blocked", 2),
        Err(SessionError::NotWritable(SessionState::Crashed))
    );
    assert!(!session.checkpoint().snapshot.clean_shutdown);
    session.recover().expect("recover to created");
    session.activate().expect("reactivate");
    session.close(true).expect("clean close");
    assert_eq!(session.state(), SessionState::Closed);
    assert_eq!(
        session.append_event("m-3", 1, MessageRole::Tool, "closed", 3),
        Err(SessionError::NotWritable(SessionState::Closed))
    );
}

#[test]
fn checkpoint_round_trip_preserves_wire_values_and_rejects_future_versions() {
    let session = Session::new(spec("session-checkpoint", 8)).expect("valid session");
    session.activate().expect("activate");
    session.append_input("m-1", "persist", 42).expect("input");
    session
        .append_event("m-2", 1, MessageRole::Tool, "result", 43)
        .expect("event");
    let checkpoint = session.checkpoint();
    assert_eq!(checkpoint.checkpoint_version, SESSION_CHECKPOINT_VERSION);
    assert_eq!(
        checkpoint.snapshot.contract_version,
        SESSION_CONTRACT_VERSION
    );
    let encoded = serde_json::to_vec(&checkpoint).expect("encode checkpoint");
    let decoded = serde_json::from_slice(&encoded).expect("decode checkpoint");
    let restored = Session::from_checkpoint(decoded).expect("restore checkpoint");
    assert_eq!(restored.snapshot(), session.snapshot());

    let mut future = checkpoint;
    future.checkpoint_version += 1;
    assert!(matches!(
        Session::from_checkpoint(future),
        Err(SessionError::InvalidSnapshot(_))
    ));
}

#[test]
fn bounded_history_and_message_ids_fail_closed() {
    let session = Session::new(spec("session-bound", 2)).expect("valid session");
    session.activate().expect("activate");
    session.append_input("m-1", "one", 1).expect("first");
    session
        .append_event("m-2", 1, MessageRole::Assistant, "two", 2)
        .expect("second");
    assert_eq!(
        session.append_event("m-2", 1, MessageRole::Tool, "duplicate", 3),
        Err(SessionError::DuplicateMessage("m-2".to_owned()))
    );
    assert_eq!(
        session.append_input("m-3", "full", 4),
        Err(SessionError::HistoryFull)
    );
    assert_eq!(
        session.messages_page(None, 0),
        Err(SessionError::InvalidPage)
    );
    assert_eq!(
        session.messages_page(Some(999), 1),
        Err(SessionError::InvalidPage)
    );
    let error_wire = serde_json::to_string(&SessionError::HistoryFull).expect("error serializes");
    assert!(error_wire.contains("history_full"));
}

#[test]
fn sharded_book_admits_parallel_sessions_and_returns_sorted_snapshots() {
    let book = Arc::new(SessionBook::new(4).expect("valid shard count"));
    let workers = (0..8)
        .map(|worker| {
            let book = Arc::clone(&book);
            thread::spawn(move || {
                for index in 0..16 {
                    let id = format!("session-{worker:02}-{index:02}");
                    let session = book.create(spec(&id, 4)).expect("session admission");
                    session.activate().expect("activate");
                    session
                        .append_input(format!("{id}-message"), "payload", index)
                        .expect("input");
                }
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().expect("session worker joins");
    }
    let snapshots = book.snapshots();
    assert_eq!(snapshots.len(), 128);
    assert!(snapshots.windows(2).all(|pair| {
        pair[0].spec.session_id < pair[1].spec.session_id
            && pair[0].messages.len() == 1
            && pair[0].next_input_seq == 2
    }));
    assert!(book.get("session-03-07").is_some());
}

#[test]
fn closed_sessions_can_be_removed_only_after_clean_close() {
    let book = SessionBook::default();
    let crashed = book
        .create(spec("session-crashed", 4))
        .expect("create crashed session");
    crashed.activate().expect("activate");
    crashed.close(false).expect("crash");
    assert!(matches!(
        book.remove_closed("session-crashed"),
        Err(SessionError::NotWritable(SessionState::Crashed))
    ));

    let clean = book
        .create(spec("session-clean", 4))
        .expect("create clean session");
    clean.activate().expect("activate");
    clean.close(true).expect("close");
    let checkpoint = book.remove_closed("session-clean").expect("remove");
    assert_eq!(checkpoint.snapshot.state, SessionState::Closed);
    assert!(book.get("session-clean").is_none());
}

#[test]
fn batch_admission_preserves_input_order_and_partial_failures() {
    let book = SessionBook::new(4).expect("valid shard count");
    book.create(spec("session-existing", 4))
        .expect("existing session");
    let results = book.create_batch(vec![
        spec("session-a", 4),
        SessionSpec::new("session-invalid", "agent-1", "cell-1", "operator", 0),
        spec("session-existing", 4),
        spec("session-b", 4),
    ]);
    assert_eq!(results.len(), 4);
    assert_eq!(
        results[0].as_ref().expect("first admitted").id(),
        "session-a"
    );
    assert!(matches!(results[1], Err(SessionError::InvalidCapacity)));
    assert!(matches!(
        results[2],
        Err(SessionError::DuplicateSession(ref id)) if id == "session-existing"
    ));
    assert_eq!(
        results[3].as_ref().expect("last admitted").id(),
        "session-b"
    );
    assert_eq!(book.snapshots().len(), 3);
}

#[test]
fn input_batch_holds_one_session_boundary_and_preserves_partial_success() {
    let session = Session::new(spec("session-input-batch", 3)).expect("valid session");
    session.activate().expect("activate");
    let results = session.append_input_batch(vec![
        SessionInput::new("message-1", "first", 1),
        SessionInput::new("message-1", "duplicate", 2),
        SessionInput::new("message-2", "second", 3),
    ]);

    assert_eq!(results.len(), 3);
    assert_eq!(results[0].as_ref().expect("first input").input_seq, 1);
    assert_eq!(
        results[1],
        Err(SessionError::DuplicateMessage("message-1".to_owned()))
    );
    assert_eq!(results[2].as_ref().expect("second input").input_seq, 2);
    assert_eq!(session.message_count(), 2);
    assert_eq!(session.snapshot().next_input_seq, 3);
    assert!(session.append_input_batch(Vec::new()).is_empty());
}
