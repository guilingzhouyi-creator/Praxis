//! Independent terminal-book tests for the Rust kernel candidate.

use l1_kernel_rs::substrate::ProcessHandle;
use l1_kernel_rs::terminal::{
    TERMINAL_MAX_FRAME_BYTES, TerminalBook, TerminalError, TerminalSpec, TerminalState,
    TerminalStream,
};
use std::sync::Arc;
use std::thread;

fn running_book() -> TerminalBook {
    let book = TerminalBook::new();
    book.register(TerminalSpec::new("term-1", 2, 2))
        .expect("register");
    book.attach("term-1", "session-1").expect("attach");
    book.bind_process("term-1", 0x0000_0001_0000_0007)
        .expect("bind");
    book.start("term-1").expect("start");
    book
}

#[test]
fn binding_is_unique_and_snapshot_is_deterministic() {
    let book = running_book();
    assert!(matches!(
        book.attach("term-1", "session-2"),
        Err(TerminalError::InvalidState { .. })
    ));
    assert!(matches!(
        book.register(TerminalSpec::new("term-1", 1, 1)),
        Err(TerminalError::DuplicateTerminal { .. })
    ));
    let snapshot = book.snapshot("term-1").expect("snapshot");
    assert_eq!(snapshot.state, TerminalState::Running);
    assert_eq!(snapshot.process_id, Some(0x0000_0001_0000_0007));
    assert_eq!(book.snapshots().len(), 1);
}

#[test]
fn mailbox_is_bounded_and_preserves_sequence() {
    let book = running_book();
    book.submit_input("term-1", b"one".to_vec()).expect("input");
    book.submit_input("term-1", b"two".to_vec()).expect("input");
    assert!(matches!(
        book.submit_input("term-1", b"three".to_vec()),
        Err(TerminalError::MailboxFull {
            stream: TerminalStream::Input
        })
    ));
    assert_eq!(
        book.take_input("term-1")
            .expect("take")
            .expect("frame")
            .sequence,
        1
    );
    assert_eq!(
        book.take_input("term-1")
            .expect("take")
            .expect("frame")
            .sequence,
        2
    );
    let snapshot = book.snapshot("term-1").expect("snapshot");
    assert_eq!(snapshot.input_dropped, 1);
    assert_eq!(snapshot.input_depth, 0);
}

#[test]
fn stop_is_terminal_and_output_can_drain() {
    let book = running_book();
    book.publish_output("term-1", TerminalStream::Output, b"done".to_vec())
        .expect("output");
    book.stop("term-1").expect("stop");
    assert!(matches!(
        book.start("term-1"),
        Err(TerminalError::InvalidState {
            state: TerminalState::Stopped,
            ..
        })
    ));
    assert_eq!(
        book.take_output("term-1")
            .expect("drain")
            .expect("frame")
            .data,
        b"done"
    );
    book.close("term-1").expect("close");
    assert!(matches!(
        book.publish_output("term-1", TerminalStream::Output, Vec::new()),
        Err(TerminalError::InvalidState {
            state: TerminalState::Closed,
            ..
        })
    ));
}

#[test]
fn invalid_frame_and_capacities_fail_closed() {
    let book = TerminalBook::new();
    assert!(matches!(
        book.register(TerminalSpec::new("term-1", 0, 1)),
        Err(TerminalError::InvalidCapacity)
    ));
    book.register(TerminalSpec::new("term-1", 1, 1))
        .expect("register");
    book.attach("term-1", "session-1").expect("attach");
    book.bind_process("term-1", 0x0000_0001_0000_0001)
        .expect("bind");
    book.start("term-1").expect("start");
    let oversized = vec![0; TERMINAL_MAX_FRAME_BYTES + 1];
    assert!(matches!(
        book.submit_input("term-1", oversized),
        Err(TerminalError::FrameTooLarge { .. })
    ));
}

#[test]
fn stale_process_handles_and_post_stop_output_fail_closed() {
    let book = TerminalBook::new();
    book.register(TerminalSpec::new("term-1", 1, 1))
        .expect("register");
    assert!(matches!(
        book.bind_process("term-1", 1),
        Err(TerminalError::InvalidIdentity)
    ));
    book.bind_process("term-1", 0x0000_0001_0000_0001)
        .expect("bind");
    book.start("term-1").expect("start");
    book.stop("term-1").expect("stop");
    assert!(matches!(
        book.publish_output("term-1", TerminalStream::Output, b"late".to_vec()),
        Err(TerminalError::InvalidState {
            state: TerminalState::Stopped,
            ..
        })
    ));
}

#[test]
fn typed_process_handle_preserves_generation_in_the_wire_snapshot() {
    let book = TerminalBook::new();
    book.register(TerminalSpec::new("term-typed", 1, 1))
        .expect("register");
    let handle = ProcessHandle::new(7, 4).expect("valid process handle");
    book.bind_process_handle("term-typed", handle)
        .expect("bind typed handle");
    assert_eq!(
        book.snapshot("term-typed").expect("snapshot").process_id,
        Some(handle.raw())
    );
}

#[test]
fn batch_mailboxes_preserve_fifo_and_item_errors() {
    let book = TerminalBook::new();
    book.register(TerminalSpec::new("term-batch", 2, 2))
        .expect("register");
    book.bind_process("term-batch", 0x0000_0001_0000_0001)
        .expect("bind");
    book.start("term-batch").expect("start");

    let results = book
        .submit_input_batch(
            "term-batch",
            vec![b"one".to_vec(), b"two".to_vec(), b"three".to_vec()],
        )
        .expect("batch submit");
    assert_eq!(results.len(), 3);
    assert!(results[0].is_ok());
    assert!(results[1].is_ok());
    assert!(matches!(
        results[2],
        Err(TerminalError::MailboxFull {
            stream: TerminalStream::Input
        })
    ));
    let frames = book.take_input_batch("term-batch", 8).expect("batch take");
    assert_eq!(
        frames
            .iter()
            .map(|frame| frame.sequence)
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    assert_eq!(frames[0].data, b"one");
    assert_eq!(frames[1].data, b"two");
    assert_eq!(
        book.snapshot("term-batch").expect("snapshot").input_dropped,
        1
    );
}

#[test]
fn output_batch_rejects_input_stream_without_losing_valid_items() {
    let book = running_book();
    let results = book
        .publish_output_batch(
            "term-1",
            vec![
                (TerminalStream::Output, b"ok".to_vec()),
                (TerminalStream::Input, b"bad".to_vec()),
                (TerminalStream::Error, b"diagnostic".to_vec()),
            ],
        )
        .expect("batch output");
    assert!(results[0].is_ok());
    assert!(matches!(
        results[1],
        Err(TerminalError::InvalidState { .. })
    ));
    assert!(results[2].is_ok());
    let frames = book.take_output_batch("term-1", 8).expect("batch drain");
    assert_eq!(frames.len(), 2);
    assert_eq!(frames[0].stream, TerminalStream::Output);
    assert_eq!(frames[1].stream, TerminalStream::Error);
}

#[test]
fn snapshots_sort_hash_registry_by_terminal_identity() {
    let book = TerminalBook::new();
    for terminal_id in ["term-z", "term-a", "term-m"] {
        book.register(TerminalSpec::new(terminal_id, 1, 1))
            .expect("register");
    }
    let ids = book
        .snapshots()
        .into_iter()
        .map(|snapshot| snapshot.terminal_id)
        .collect::<Vec<_>>();
    assert_eq!(ids, vec!["term-a", "term-m", "term-z"]);
}

#[test]
fn independent_terminal_mailboxes_progress_concurrently() {
    let book = Arc::new(TerminalBook::new());
    for (terminal_id, process_id) in [
        ("term-concurrent-a", 0x0000_0001_0000_0001),
        ("term-concurrent-b", 0x0000_0001_0000_0002),
    ] {
        book.register(TerminalSpec::new(terminal_id, 8, 8))
            .expect("register");
        book.bind_process(terminal_id, process_id).expect("bind");
        book.start(terminal_id).expect("start");
    }

    let workers = ["term-concurrent-a", "term-concurrent-b"]
        .into_iter()
        .map(|terminal_id| {
            let book = Arc::clone(&book);
            thread::spawn(move || {
                for sequence in 0..128_u64 {
                    let payload = sequence.to_le_bytes().to_vec();
                    book.submit_input(terminal_id, payload.clone())
                        .expect("submit");
                    let frame = book.take_input(terminal_id).expect("take").expect("frame");
                    assert_eq!(frame.data, payload);
                }
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().expect("worker completes");
    }
}
