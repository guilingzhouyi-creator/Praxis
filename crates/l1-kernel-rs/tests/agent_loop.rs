//! Independent tests for logical AgentLoop routing and session admission.

use std::sync::{Arc, Barrier};

use l1_kernel_rs::agent_loop::{
    AgentLoopBook, AgentLoopError, AgentLoopEvent, AgentLoopSpec, AgentLoopState,
};
use l1_kernel_rs::session::{MessageRole, SessionBook, SessionInput, SessionSpec, SessionState};
use l1_kernel_rs::terminal::{TerminalBook, TerminalSpec};

fn setup() -> (AgentLoopBook, SessionBook, TerminalBook) {
    let sessions = SessionBook::new(2).expect("session book");
    let session = sessions
        .create(SessionSpec::new(
            "session-1",
            "agent-1",
            "cell-1",
            "worker",
            16,
        ))
        .expect("session create");
    session.activate().expect("session activate");

    let terminals = TerminalBook::new();
    terminals
        .register(TerminalSpec::new("terminal-1", 8, 8))
        .expect("terminal register");
    terminals
        .attach("terminal-1", "session-1")
        .expect("terminal attach");

    (AgentLoopBook::new(), sessions, terminals)
}

fn loop_spec() -> AgentLoopSpec {
    AgentLoopSpec::new("loop-1", "agent-1", "cell-1", "session-1", "terminal-1")
}

#[test]
fn lifecycle_attachment_and_message_sequences_are_explicit() {
    let (loops, sessions, terminals) = setup();
    let session = sessions.get("session-1").expect("session exists");
    assert_eq!(session.state(), SessionState::Active);
    assert_eq!(
        loops.register(loop_spec()).expect("register").state,
        AgentLoopState::Created
    );
    assert_eq!(
        loops
            .attach("loop-1", &session, &terminals)
            .expect("attach")
            .state,
        AgentLoopState::Ready
    );
    loops.start("loop-1").expect("start");

    let input = loops
        .admit_input("loop-1", &session, "message-1", "hello", 10)
        .expect("input");
    assert_eq!(input.command_seq, 1);
    assert_eq!(input.message_seq, 1);
    assert_eq!(input.input_seq, 1);

    let event = loops
        .admit_event(
            "loop-1",
            &session,
            AgentLoopEvent::new("message-2", 1, MessageRole::Assistant, "world", 11),
        )
        .expect("event");
    assert_eq!(event.command_seq, 2);
    assert_eq!(event.message_seq, 2);
    assert_eq!(event.input_seq, 1);

    let page = session.messages_page(None, 8).expect("page");
    assert_eq!(page.items.len(), 2);
    assert_eq!(page.items[0].content, "hello");
    assert_eq!(page.items[1].role, MessageRole::Assistant);
    let snapshot = loops.snapshot("loop-1").expect("snapshot");
    assert_eq!(snapshot.next_command_seq, 3);
    assert_eq!(snapshot.accepted_commands, 2);
    assert_eq!(snapshot.failed_commands, 0);
    assert_eq!(snapshot.lock_wait_ns, 0);
}

#[test]
fn failed_session_admission_is_counted_without_advancing_sequence() {
    let (loops, sessions, terminals) = setup();
    let session = sessions.get("session-1").expect("session exists");
    loops.register(loop_spec()).expect("register");
    loops
        .attach("loop-1", &session, &terminals)
        .expect("attach");
    loops.start("loop-1").expect("start");
    loops
        .admit_input("loop-1", &session, "message-1", "hello", 10)
        .expect("first input");
    assert!(matches!(
        loops.admit_input("loop-1", &session, "message-1", "duplicate", 11),
        Err(AgentLoopError::Session(_))
    ));
    let snapshot = loops.snapshot("loop-1").expect("snapshot");
    assert_eq!(snapshot.next_command_seq, 2);
    assert_eq!(snapshot.accepted_commands, 1);
    assert_eq!(snapshot.failed_commands, 1);
}

#[test]
fn input_batch_preserves_order_and_only_successes_consume_command_sequences() {
    let (loops, sessions, terminals) = setup();
    let session = sessions.get("session-1").expect("session exists");
    loops.register(loop_spec()).expect("register");
    loops
        .attach("loop-1", &session, &terminals)
        .expect("attach");
    loops.start("loop-1").expect("start");

    let results = loops
        .admit_input_batch(
            "loop-1",
            &session,
            vec![
                SessionInput::new("message-1", "first", 10),
                SessionInput::new("message-1", "duplicate", 11),
                SessionInput::new("message-2", "second", 12),
            ],
        )
        .expect("batch lookup");

    assert_eq!(results.len(), 3);
    assert_eq!(results[0].as_ref().expect("first receipt").command_seq, 1);
    assert!(matches!(results[1], Err(AgentLoopError::Session(_))));
    assert_eq!(results[2].as_ref().expect("second receipt").command_seq, 2);
    let snapshot = loops.snapshot("loop-1").expect("snapshot");
    assert_eq!(snapshot.next_command_seq, 3);
    assert_eq!(snapshot.accepted_commands, 2);
    assert_eq!(snapshot.failed_commands, 1);
    assert_eq!(session.message_count(), 2);
    assert!(
        loops
            .admit_input_batch("loop-1", &session, Vec::new())
            .expect("empty batch lookup")
            .is_empty()
    );
}

#[test]
fn input_batch_counts_rejections_before_session_admission() {
    let (loops, sessions, terminals) = setup();
    let session = sessions.get("session-1").expect("session exists");
    loops.register(loop_spec()).expect("register");
    loops
        .attach("loop-1", &session, &terminals)
        .expect("attach");
    let results = loops
        .admit_input_batch(
            "loop-1",
            &session,
            vec![
                SessionInput::new("message-1", "blocked", 10),
                SessionInput::new("message-2", "blocked", 11),
            ],
        )
        .expect("batch lookup");
    assert!(results.iter().all(|result| matches!(
        result,
        Err(AgentLoopError::NotRunning(AgentLoopState::Ready))
    )));
    assert_eq!(
        loops.snapshot("loop-1").expect("snapshot").failed_commands,
        2
    );
}

#[test]
fn pause_and_stop_close_message_admission_without_touching_terminal_io() {
    let (loops, sessions, terminals) = setup();
    let session = sessions.get("session-1").expect("session exists");
    loops.register(loop_spec()).expect("register");
    loops
        .attach("loop-1", &session, &terminals)
        .expect("attach");
    loops.start("loop-1").expect("start");
    assert_eq!(
        loops.pause("loop-1").expect("pause").state,
        AgentLoopState::Paused
    );
    assert!(matches!(
        loops.admit_input("loop-1", &session, "message-1", "blocked", 10),
        Err(AgentLoopError::NotRunning(AgentLoopState::Paused))
    ));
    loops.resume("loop-1").expect("resume");
    loops.stop("loop-1", true).expect("stop");
    assert!(matches!(
        loops.admit_input("loop-1", &session, "message-2", "blocked", 11),
        Err(AgentLoopError::NotRunning(AgentLoopState::Stopped))
    ));
    assert_eq!(
        terminals
            .snapshot("terminal-1")
            .expect("terminal")
            .input_depth,
        0
    );
    assert_eq!(session.state(), SessionState::Active);
}

#[test]
fn attachment_rejects_identity_or_terminal_correlation_mismatch() {
    let (loops, sessions, terminals) = setup();
    let session = sessions.get("session-1").expect("session exists");
    loops.register(loop_spec()).expect("register");
    let wrong_session = sessions
        .create(SessionSpec::new(
            "session-2",
            "agent-2",
            "cell-1",
            "worker",
            8,
        ))
        .expect("wrong session");
    assert_eq!(
        loops.attach("loop-1", &wrong_session, &terminals),
        Err(AgentLoopError::SessionMismatch)
    );
    assert_eq!(
        loops
            .attach("loop-1", &session, &terminals)
            .expect("attach")
            .state,
        AgentLoopState::Ready
    );
    loops
        .register(AgentLoopSpec::new(
            "loop-2",
            "agent-1",
            "cell-1",
            "session-1",
            "missing-terminal",
        ))
        .expect("second register");
    assert!(matches!(
        loops.attach("loop-2", &session, &terminals),
        Err(AgentLoopError::Terminal(_))
    ));
}

#[test]
fn concurrent_admission_keeps_session_and_command_sequences_unique() {
    let (loops, sessions, terminals) = setup();
    let session = sessions.get("session-1").expect("session exists");
    loops.register(loop_spec()).expect("register");
    loops
        .attach("loop-1", &session, &terminals)
        .expect("attach");
    loops.start("loop-1").expect("start");

    let handle = Arc::new(loops.handle("loop-1").expect("handle"));
    let barrier = Arc::new(Barrier::new(4));
    let workers = (0..4)
        .map(|worker| {
            let handle = Arc::clone(&handle);
            let session = Arc::clone(&session);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                (0..4)
                    .map(|item| {
                        handle
                            .admit_input(
                                &session,
                                format!("concurrent-{worker}-{item}"),
                                "payload",
                                (worker * 4 + item) as u64,
                            )
                            .expect("concurrent admission")
                    })
                    .collect::<Vec<_>>()
            })
        })
        .collect::<Vec<_>>();
    let mut receipts = workers
        .into_iter()
        .flat_map(|worker| worker.join().expect("worker join"))
        .collect::<Vec<_>>();

    receipts.sort_unstable_by_key(|receipt| receipt.command_seq);
    assert_eq!(receipts.len(), 16);
    assert_eq!(
        receipts
            .iter()
            .map(|receipt| receipt.command_seq)
            .collect::<Vec<_>>(),
        (1..=16).collect::<Vec<_>>()
    );
    let mut input_sequences = receipts
        .iter()
        .map(|receipt| receipt.input_seq)
        .collect::<Vec<_>>();
    input_sequences.sort_unstable();
    assert_eq!(input_sequences, (1..=16).collect::<Vec<_>>());

    let snapshot = loops.snapshot("loop-1").expect("snapshot");
    assert_eq!(snapshot.next_command_seq, 17);
    assert_eq!(snapshot.accepted_commands, 16);
    assert_eq!(snapshot.failed_commands, 0);
    assert_eq!(session.message_count(), 16);
    loops.stop("loop-1", true).expect("stop");
    assert_eq!(
        loops.snapshot("loop-1").expect("stopped snapshot").state,
        AgentLoopState::Stopped
    );
}
