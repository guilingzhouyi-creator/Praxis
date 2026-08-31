//! Independent tests for the terminal-backed AgentLoop composition bridge.

use std::sync::Arc;
use std::time::Duration;

use l1_kernel_rs::agent_loop::{AgentLoopEvent, AgentLoopSpec};
use l1_kernel_rs::agent_loop_terminal::{
    AGENT_LOOP_TERMINAL_CONTRACT_VERSION, AgentLoopTerminalBridge, AgentLoopTerminalError,
};
use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig};
use l1_kernel_rs::session::{MessageRole, Session, SessionInput, SessionSpec};
use l1_kernel_rs::substrate::ProcessHandle;
use l1_kernel_rs::terminal::{TerminalFrame, TerminalSpec, TerminalStream};
use l1_kernel_rs::worker::WorkerConfig;

fn runtime() -> (KernelRuntime, Arc<Session>) {
    let runtime = KernelRuntime::new(
        AssemblySpec::new(
            "state",
            vec![
                BootStepSpec::new("state", Vec::new()),
                BootStepSpec::new("runtime", vec!["state".to_owned()]),
            ],
            Vec::new(),
        ),
        RuntimeConfig::new(4, 2, WorkerConfig::new(1, 2, 8, Duration::from_millis(20))),
    )
    .expect("runtime");
    runtime.boot().expect("boot");
    let session = runtime
        .sessions()
        .create(SessionSpec::new(
            "session-1",
            "agent-1",
            "cell-1",
            "worker",
            32,
        ))
        .expect("session");
    session.activate().expect("activate");
    runtime
        .terminals()
        .register(TerminalSpec::new("terminal-1", 8, 8))
        .expect("terminal");
    runtime
        .terminals()
        .attach("terminal-1", "session-1")
        .expect("terminal session");
    runtime
        .terminals()
        .bind_process(
            "terminal-1",
            ProcessHandle::new(1, 1).expect("process handle").raw(),
        )
        .expect("terminal process");
    runtime
        .terminals()
        .start("terminal-1")
        .expect("terminal start");
    runtime
        .agent_loops()
        .register(AgentLoopSpec::new(
            "loop-1",
            "agent-1",
            "cell-1",
            "session-1",
            "terminal-1",
        ))
        .expect("loop");
    runtime
        .agent_loops()
        .attach("loop-1", &session, runtime.terminals())
        .expect("loop attach");
    runtime.agent_loops().start("loop-1").expect("loop start");
    (runtime, session)
}

fn decoder(frame: &TerminalFrame) -> Result<SessionInput, String> {
    let content =
        String::from_utf8(frame.data.clone()).map_err(|_| "input is not UTF-8".to_owned())?;
    Ok(SessionInput::new(
        format!("terminal-input-{}", frame.sequence),
        content,
        frame.sequence,
    ))
}

#[test]
fn binding_is_explicit_and_versioned() {
    let (runtime, session) = runtime();
    let bridge = AgentLoopTerminalBridge::new(&runtime, decoder);
    let binding = bridge
        .binding("loop-1", &session, "terminal-1")
        .expect("binding");
    assert_eq!(
        binding.contract_version,
        AGENT_LOOP_TERMINAL_CONTRACT_VERSION
    );
    assert_eq!(binding.spec.loop_id, "loop-1");
    assert_eq!(binding.session_id, "session-1");
    assert_eq!(binding.terminal_state.as_str(), "running");
}

#[test]
fn submitted_terminal_frame_reaches_session_and_action() {
    let (runtime, session) = runtime();
    runtime
        .terminals()
        .submit_input("terminal-1", b"hello".to_vec())
        .expect("input");
    let frame = runtime
        .terminals()
        .take_input("terminal-1")
        .expect("take input")
        .expect("frame");
    let bridge = AgentLoopTerminalBridge::new(&runtime, decoder);
    let task = bridge
        .submit_frame(
            "loop-1",
            Arc::clone(&session),
            "terminal-1",
            frame,
            Box::new(|context| {
                Ok(Some(AgentLoopEvent::new(
                    "assistant-1",
                    context.receipt.input_seq,
                    MessageRole::Assistant,
                    "world",
                    12,
                )))
            }),
        )
        .expect("submit");
    let report = task.result(Some(Duration::from_secs(1))).expect("report");
    assert_eq!(report.input.input_seq, 1);
    assert_eq!(report.event.expect("event").input_seq, 1);
    assert_eq!(session.message_count(), 2);
    bridge
        .publish_output(
            "loop-1",
            &session,
            "terminal-1",
            TerminalStream::Output,
            b"world".to_vec(),
        )
        .expect("output");
    assert_eq!(
        runtime
            .terminals()
            .take_output("terminal-1")
            .expect("take output")
            .expect("output frame")
            .data,
        b"world"
    );
    l1_kernel_rs::agent_loop_execution::AgentLoopExecutionBridge::new(&runtime)
        .reap(&task)
        .expect("reap");
}

#[test]
fn decode_or_correlation_failure_happens_before_admission() {
    let (runtime, session) = runtime();
    let bridge = AgentLoopTerminalBridge::new(&runtime, |frame: &TerminalFrame| {
        if frame.data == b"bad" {
            return Err("decoder rejected frame".to_owned());
        }
        decoder(frame)
    });
    let result = bridge.submit_batch(
        "loop-1",
        Arc::clone(&session),
        "terminal-1",
        vec![TerminalFrame {
            sequence: 1,
            stream: TerminalStream::Input,
            data: b"bad".to_vec(),
        }],
        vec![Box::new(|_| Ok(None))],
    );
    assert!(matches!(
        result,
        Err(AgentLoopTerminalError::Decoder(reason)) if reason == "decoder rejected frame"
    ));
    assert_eq!(session.message_count(), 0);

    let mismatch = bridge.submit_frame(
        "loop-1",
        Arc::clone(&session),
        "other-terminal",
        TerminalFrame {
            sequence: 2,
            stream: TerminalStream::Input,
            data: b"hello".to_vec(),
        },
        Box::new(|_| Ok(None)),
    );
    assert!(matches!(
        mismatch,
        Err(AgentLoopTerminalError::InvalidBinding(_))
    ));
    assert_eq!(session.message_count(), 0);
}

#[test]
fn invalid_frames_and_batch_limits_fail_closed() {
    let (runtime, session) = runtime();
    let bridge =
        AgentLoopTerminalBridge::with_max_batch(&runtime, decoder, 1).expect("bounded bridge");
    let invalid_stream = bridge.submit_frame(
        "loop-1",
        Arc::clone(&session),
        "terminal-1",
        TerminalFrame {
            sequence: 1,
            stream: TerminalStream::Output,
            data: b"wrong direction".to_vec(),
        },
        Box::new(|_| Ok(None)),
    );
    assert!(matches!(
        invalid_stream,
        Err(AgentLoopTerminalError::InvalidFrame(_))
    ));
    let too_large = bridge.submit_batch(
        "loop-1",
        Arc::clone(&session),
        "terminal-1",
        vec![
            TerminalFrame {
                sequence: 1,
                stream: TerminalStream::Input,
                data: b"one".to_vec(),
            },
            TerminalFrame {
                sequence: 2,
                stream: TerminalStream::Input,
                data: b"two".to_vec(),
            },
        ],
        vec![Box::new(|_| Ok(None)), Box::new(|_| Ok(None))],
    );
    assert!(matches!(
        too_large,
        Err(AgentLoopTerminalError::BatchTooLarge { size: 2, limit: 1 })
    ));
    assert_eq!(session.message_count(), 0);
}

#[test]
fn output_batch_preserves_capacity_results_without_accepting_input_stream() {
    let (runtime, session) = runtime();
    let bridge = AgentLoopTerminalBridge::new(&runtime, decoder);
    let error = bridge.publish_output_batch(
        "loop-1",
        &session,
        "terminal-1",
        vec![
            (TerminalStream::Output, b"ok".to_vec()),
            (TerminalStream::Input, b"bad".to_vec()),
        ],
    );
    assert!(matches!(
        error,
        Err(AgentLoopTerminalError::InvalidFrame(_))
    ));
    assert_eq!(
        runtime
            .terminals()
            .snapshot("terminal-1")
            .expect("snapshot")
            .output_depth,
        0
    );
}
