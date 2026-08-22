//! Contract tests for the Rust-owned terminal/session substrate.

use l1_kernel_rs::substrate::ProcessHandle;
use l1_kernel_rs::terminal::{TerminalBook, TerminalSpec, TerminalState, TerminalStream};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct TerminalVectors {
    terminal_id: String,
    session_id: String,
    process_id: u64,
    input_capacity: usize,
    output_capacity: usize,
    input: Vec<String>,
    output: String,
    expected_state: String,
    expected_input_sequences: Vec<u64>,
    expected_output_sequence: u64,
}

#[test]
fn terminal_vectors_preserve_identity_lifecycle_and_bounded_streams() {
    let vectors: TerminalVectors = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_terminal_vectors.json"
    ))
    .expect("valid terminal vectors");
    let book = TerminalBook::new();
    book.register(TerminalSpec::new(
        vectors.terminal_id.clone(),
        vectors.input_capacity,
        vectors.output_capacity,
    ))
    .expect("register");
    book.attach(&vectors.terminal_id, vectors.session_id)
        .expect("attach");
    let process_handle = ProcessHandle::from_raw(vectors.process_id).expect("valid process handle");
    book.bind_process_handle(&vectors.terminal_id, process_handle)
        .expect("bind process");
    book.start(&vectors.terminal_id).expect("start");
    for item in &vectors.input {
        book.submit_input(&vectors.terminal_id, item.as_bytes().to_vec())
            .expect("submit input");
    }
    book.publish_output(
        &vectors.terminal_id,
        TerminalStream::Output,
        vectors.output.as_bytes().to_vec(),
    )
    .expect("publish output");

    let snapshot = book.snapshot(&vectors.terminal_id).expect("snapshot");
    assert_eq!(snapshot.state, TerminalState::Running);
    assert_eq!(snapshot.state.as_str(), vectors.expected_state);
    let input_sequences = vectors
        .input
        .iter()
        .map(|_| {
            book.take_input(&vectors.terminal_id)
                .expect("take input")
                .expect("frame")
                .sequence
        })
        .collect::<Vec<_>>();
    assert_eq!(input_sequences, vectors.expected_input_sequences);
    assert_eq!(
        book.take_output(&vectors.terminal_id)
            .expect("take output")
            .expect("frame")
            .sequence,
        vectors.expected_output_sequence
    );
}
