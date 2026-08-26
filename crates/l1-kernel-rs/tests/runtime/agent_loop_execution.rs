//! Independent AgentLoop execution-bridge tests for the Rust runtime.

use std::sync::{Arc, Barrier};
use std::time::Duration;

use l1_kernel_rs::agent_loop::{AgentLoopEvent, AgentLoopSpec};
use l1_kernel_rs::agent_loop_execution::{
    AgentLoopAction, AgentLoopExecutionBridge, AgentLoopExecutionError, AgentLoopExecutionRequest,
    AgentLoopExecutionStage, AgentLoopExecutionWaitError,
};
use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig, RuntimeTaskState};
use l1_kernel_rs::session::{MessageRole, SessionInput, SessionSpec};
use l1_kernel_rs::terminal::TerminalSpec;
use l1_kernel_rs::worker::WorkerConfig;

fn runtime() -> KernelRuntime {
    let runtime = KernelRuntime::new(
        AssemblySpec::new(
            "state",
            vec![
                BootStepSpec::new("state", Vec::new()),
                BootStepSpec::new("runtime", vec!["state".to_owned()]),
            ],
            Vec::new(),
        ),
        RuntimeConfig::new(4, 2, WorkerConfig::new(1, 2, 4, Duration::from_millis(20))),
    )
    .expect("runtime");
    runtime.boot().expect("boot");
    runtime
}

fn attached_loop(runtime: &KernelRuntime) -> Arc<l1_kernel_rs::session::Session> {
    let session = runtime
        .sessions()
        .create(SessionSpec::new(
            "session-1",
            "agent-1",
            "cell-1",
            "worker",
            16,
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
        .expect("terminal attach");
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
    session
}

#[test]
fn bridge_admits_input_runs_action_and_admits_event() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let action: AgentLoopAction = Box::new(|context| {
        Ok(Some(AgentLoopEvent::new(
            "assistant-1",
            context.receipt.input_seq,
            MessageRole::Assistant,
            "ready",
            11,
        )))
    });
    let task = bridge
        .submit_input(
            "loop-1",
            Arc::clone(&session),
            SessionInput::new("input-1", "hello", 10),
            action,
        )
        .expect("submit");
    let report = task.result(Some(Duration::from_secs(1))).expect("report");
    assert_eq!(report.input.command_seq, 1);
    assert_eq!(report.input.input_seq, 1);
    assert_eq!(report.event.expect("event").message_seq, 2);
    assert_eq!(session.message_count(), 2);
    assert_eq!(task.state(), Some(RuntimeTaskState::Succeeded));
    bridge.reap(&task).expect("reap");
}

#[test]
fn bridge_reports_action_failure_with_admitted_input_receipt() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let task = bridge
        .submit_input(
            "loop-1",
            Arc::clone(&session),
            SessionInput::new("input-1", "hello", 10),
            Box::new(|_| Err("provider unavailable".to_owned())),
        )
        .expect("submit");
    let error = task
        .result(Some(Duration::from_secs(1)))
        .expect_err("failure");
    match error {
        AgentLoopExecutionWaitError::Execution(failure) => {
            assert_eq!(failure.stage, AgentLoopExecutionStage::Action);
            assert_eq!(failure.input.expect("input").input_seq, 1);
            assert_eq!(failure.reason, "provider unavailable");
        }
        other => panic!("unexpected error: {other:?}"),
    }
    assert_eq!(session.message_count(), 1);
    bridge.reap(&task).expect("reap");
}

#[test]
fn bridge_reports_event_failure_with_partial_input_receipt() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let task = bridge
        .submit_input(
            "loop-1",
            Arc::clone(&session),
            SessionInput::new("input-1", "hello", 10),
            Box::new(|_| {
                Ok(Some(AgentLoopEvent::new(
                    "assistant-1",
                    999,
                    MessageRole::Assistant,
                    "wrong correlation",
                    11,
                )))
            }),
        )
        .expect("submit");
    let error = task
        .result(Some(Duration::from_secs(1)))
        .expect_err("failure");
    match error {
        AgentLoopExecutionWaitError::Execution(failure) => {
            assert_eq!(failure.stage, AgentLoopExecutionStage::EventAdmission);
            assert_eq!(failure.input.expect("input").input_seq, 1);
            assert!(failure.agent_loop_error.is_some());
        }
        other => panic!("unexpected error: {other:?}"),
    }
    assert_eq!(session.message_count(), 1);
    bridge.reap(&task).expect("reap");
}

#[test]
fn bridge_converts_action_panic_into_structured_failure() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let task = bridge
        .submit_input(
            "loop-1",
            Arc::clone(&session),
            SessionInput::new("input-1", "hello", 10),
            Box::new(|_| panic!("action panic")),
        )
        .expect("submit");
    let error = task
        .result(Some(Duration::from_secs(1)))
        .expect_err("failure");
    match error {
        AgentLoopExecutionWaitError::Execution(failure) => {
            assert_eq!(failure.stage, AgentLoopExecutionStage::Action);
            assert_eq!(failure.reason, "execution action panicked");
            assert_eq!(failure.input.expect("input").input_seq, 1);
        }
        other => panic!("unexpected error: {other:?}"),
    }
    bridge.reap(&task).expect("reap");
}

#[test]
fn bridge_preflights_identity_and_state_without_queuing_work() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let wrong = runtime
        .sessions()
        .create(SessionSpec::new(
            "session-2",
            "agent-1",
            "cell-1",
            "worker",
            16,
        ))
        .expect("wrong session");
    assert!(matches!(
        bridge.submit_input(
            "loop-1",
            wrong,
            SessionInput::new("input-1", "hello", 10),
            Box::new(|_| Ok(None)),
        ),
        Err(AgentLoopExecutionError::AgentLoop(
            l1_kernel_rs::agent_loop::AgentLoopError::SessionMismatch
        ))
    ));
    runtime.agent_loops().stop("loop-1", true).expect("stop");
    assert!(matches!(
        bridge.submit_input(
            "loop-1",
            session,
            SessionInput::new("input-2", "blocked", 11),
            Box::new(|_| Ok(None)),
        ),
        Err(AgentLoopExecutionError::AgentLoop(
            l1_kernel_rs::agent_loop::AgentLoopError::NotRunning(_)
        ))
    ));
}

#[test]
fn cancellation_before_worker_execution_does_not_admit_input() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let task = bridge
        .submit_input_with_timeout(
            "loop-1",
            Arc::clone(&session),
            SessionInput::new("input-1", "hello", 10),
            Box::new(|_| Ok(None)),
            Duration::from_secs(1),
        )
        .expect("submit");
    let _ = task.cancel("test cancellation");
    let result = task.result(Some(Duration::from_secs(1)));
    if result.is_ok() {
        assert_eq!(session.message_count(), 1);
    } else {
        assert!(matches!(result, Err(AgentLoopExecutionWaitError::Task(_))));
        assert_eq!(session.message_count(), 0);
    }
    bridge.reap(&task).expect("reap");
}

#[test]
fn grouped_execution_reserves_work_before_admitting_inputs() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let requests = vec![
        AgentLoopExecutionRequest::new(
            SessionInput::new("input-1", "hello", 10),
            Box::new(|context| {
                Ok(Some(AgentLoopEvent::new(
                    "assistant-1",
                    context.receipt.input_seq,
                    MessageRole::Assistant,
                    "one",
                    11,
                )))
            }),
        ),
        AgentLoopExecutionRequest::new(
            SessionInput::new("input-2", "world", 12),
            Box::new(|context| {
                Ok(Some(AgentLoopEvent::new(
                    "assistant-2",
                    context.receipt.input_seq,
                    MessageRole::Assistant,
                    "two",
                    13,
                )))
            }),
        ),
    ];
    let tasks = bridge
        .submit_input_batch("loop-1", Arc::clone(&session), requests)
        .expect("submit batch");
    assert_eq!(tasks.len(), 2);
    let reports = tasks
        .iter()
        .map(|task| task.result(Some(Duration::from_secs(1))).expect("report"))
        .collect::<Vec<_>>();
    assert_eq!(reports[0].input.input_seq, 1);
    assert_eq!(reports[1].input.input_seq, 2);
    assert_eq!(session.message_count(), 4);
    for task in &tasks {
        bridge.reap(task).expect("reap");
    }
}

#[test]
fn empty_group_is_a_noop_and_preflight_failure_does_not_queue_work() {
    let runtime = runtime();
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    assert!(
        bridge
            .submit_input_batch("loop-1", Arc::clone(&session), Vec::new())
            .expect("empty batch")
            .is_empty()
    );
    let wrong = runtime
        .sessions()
        .create(SessionSpec::new(
            "session-2",
            "agent-1",
            "cell-1",
            "worker",
            16,
        ))
        .expect("wrong session");
    let error = bridge.submit_input_batch(
        "loop-1",
        wrong,
        vec![AgentLoopExecutionRequest::new(
            SessionInput::new("input-1", "blocked", 10),
            Box::new(|_| Ok(None)),
        )],
    );
    assert!(matches!(
        error,
        Err(AgentLoopExecutionError::AgentLoop(
            l1_kernel_rs::agent_loop::AgentLoopError::SessionMismatch
        ))
    ));
    assert_eq!(session.message_count(), 0);
}

#[test]
fn grouped_execution_rolls_back_all_reservations_on_capacity_failure() {
    let runtime = KernelRuntime::new(
        AssemblySpec::new(
            "state",
            vec![
                BootStepSpec::new("state", Vec::new()),
                BootStepSpec::new("runtime", vec!["state".to_owned()]),
            ],
            Vec::new(),
        ),
        RuntimeConfig::new(2, 2, WorkerConfig::new(1, 2, 4, Duration::from_millis(20))),
    )
    .expect("runtime");
    runtime.boot().expect("boot");
    let session = attached_loop(&runtime);
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let requests = (0..3)
        .map(|index| {
            AgentLoopExecutionRequest::new(
                SessionInput::new(format!("input-{index}"), "blocked", index as u64),
                Box::new(|_| Ok(None)),
            )
        })
        .collect();
    let error = bridge.submit_input_batch("loop-1", session, requests);
    assert!(matches!(
        error,
        Err(AgentLoopExecutionError::Runtime(
            l1_kernel_rs::runtime::RuntimeError::Scheduler(
                l1_kernel_rs::scheduler::SchedulerError::CapacityExhausted
            )
        ))
    ));
    assert_eq!(runtime.snapshot().task_count, 0);
}

#[test]
fn grouped_execution_rejects_when_worker_queue_cannot_retain_the_group() {
    let runtime = KernelRuntime::new(
        AssemblySpec::new(
            "state",
            vec![
                BootStepSpec::new("state", Vec::new()),
                BootStepSpec::new("runtime", vec!["state".to_owned()]),
            ],
            Vec::new(),
        ),
        RuntimeConfig::new(8, 2, WorkerConfig::new(1, 1, 1, Duration::from_millis(20))),
    )
    .expect("runtime");
    runtime.boot().expect("boot");
    let session = attached_loop(&runtime);
    let started = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let blocker = runtime
        .submit(Box::new({
            let started = Arc::clone(&started);
            let release = Arc::clone(&release);
            move || {
                started.wait();
                release.wait();
                Ok(serde_json::Value::Null)
            }
        }))
        .expect("blocker");
    started.wait();
    let queued = runtime
        .submit(Box::new(|| Ok(serde_json::Value::Null)))
        .expect("queued");
    let bridge = AgentLoopExecutionBridge::new(&runtime);
    let error = bridge.submit_input_batch(
        "loop-1",
        session,
        vec![AgentLoopExecutionRequest::new(
            SessionInput::new("input-1", "blocked", 10),
            Box::new(|_| Ok(None)),
        )],
    );
    assert!(matches!(
        error,
        Err(AgentLoopExecutionError::Runtime(
            l1_kernel_rs::runtime::RuntimeError::WorkerRejected(_)
        ))
    ));
    assert_eq!(runtime.snapshot().task_count, 2);
    release.wait();
    blocker
        .result(Some(Duration::from_secs(1)))
        .expect("blocker result");
    queued
        .result(Some(Duration::from_secs(1)))
        .expect("queued result");
    runtime.reap(blocker.handle()).expect("reap blocker");
    runtime.reap(queued.handle()).expect("reap queued");
    assert_eq!(runtime.snapshot().task_count, 0);
}
