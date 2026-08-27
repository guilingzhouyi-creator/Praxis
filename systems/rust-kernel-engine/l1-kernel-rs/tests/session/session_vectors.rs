//! Shared session vectors for the Rust/TS-neutral session truth boundary.

use l1_kernel_rs::session::{MessageRole, Session, SessionSpec, SessionState};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct Vectors {
    schema_version: u32,
    spec: SessionSpec,
    inputs: Vec<InputVector>,
    events: Vec<EventVector>,
    expected: ExpectedVector,
}

#[derive(Debug, Deserialize)]
struct InputVector {
    message_id: String,
    content: String,
    created_at_ns: u64,
}

#[derive(Debug, Deserialize)]
struct EventVector {
    message_id: String,
    input_seq: u64,
    role: MessageRole,
    content: String,
    created_at_ns: u64,
}

#[derive(Debug, Deserialize)]
struct ExpectedVector {
    state: SessionState,
    next_input_seq: u64,
    next_message_seq: u64,
    message_sequences: Vec<u64>,
    input_sequences: Vec<u64>,
    page_limit: usize,
    page_next_cursor: u64,
}

#[test]
fn shared_session_vectors_match_public_candidate_api() {
    let vectors: Vectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_session_vectors.json"
    ))
    .expect("session fixture decodes");
    assert_eq!(vectors.schema_version, 1);
    let session = Session::new(vectors.spec).expect("fixture spec is valid");
    session.activate().expect("activate");
    for input in vectors.inputs {
        session
            .append_input(input.message_id, input.content, input.created_at_ns)
            .expect("input admitted");
    }
    for event in vectors.events {
        session
            .append_event(
                event.message_id,
                event.input_seq,
                event.role,
                event.content,
                event.created_at_ns,
            )
            .expect("event admitted");
    }

    let snapshot = session.snapshot();
    assert_eq!(snapshot.state, vectors.expected.state);
    assert_eq!(snapshot.next_input_seq, vectors.expected.next_input_seq);
    assert_eq!(snapshot.next_message_seq, vectors.expected.next_message_seq);
    assert_eq!(
        snapshot
            .messages
            .iter()
            .map(|message| message.sequence)
            .collect::<Vec<_>>(),
        vectors.expected.message_sequences
    );
    assert_eq!(
        snapshot
            .messages
            .iter()
            .map(|message| message.input_seq)
            .collect::<Vec<_>>(),
        vectors.expected.input_sequences
    );
    let page = session
        .messages_page(None, vectors.expected.page_limit)
        .expect("page");
    assert_eq!(page.next_cursor, Some(vectors.expected.page_next_cursor));
}
