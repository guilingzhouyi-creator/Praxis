//! Independent execution-host tests for the Rust kernel runtime candidate.

use std::collections::BTreeMap;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::contract::{CapabilityRequest, CapabilityResult, JsonObject, JsonValue};
use l1_kernel_rs::gatechain::{GateDecision, GateRequest};
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig, RuntimeError, RuntimeTaskState};
use l1_kernel_rs::worker::{TaskHandleError, WorkerConfig};
use serde_json::json;

fn spec(state_root: impl Into<String>) -> AssemblySpec {
    AssemblySpec::new(
        state_root,
        vec![
            BootStepSpec::new("state", Vec::new()),
            BootStepSpec::new("runtime", vec!["state".to_owned()]),
        ],
        vec![PortDescriptor::new("worker", PortKind::Worker, 1)],
    )
}

fn config(max_processes: u32, queue_size: usize) -> RuntimeConfig {
    RuntimeConfig::new(
        max_processes,
        2,
        WorkerConfig::new(1, 1, queue_size, Duration::from_millis(20)),
    )
}

fn runtime(max_processes: u32, queue_size: usize) -> KernelRuntime {
    KernelRuntime::new(spec("state"), config(max_processes, queue_size)).expect("valid runtime")
}

fn temp_root() -> std::path::PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "praxis-kernel-runtime-{}-{nanos}",
        std::process::id()
    ))
}

fn capability_request() -> CapabilityRequest {
    CapabilityRequest {
        agent_id: "shell".to_owned(),
        name: "read_file".to_owned(),
        args: JsonObject::from([("path".to_owned(), JsonValue::String("/tmp/x".to_owned()))]),
        domain: "runtime-test".to_owned(),
        nature: "read".to_owned(),
        interactive: true,
    }
}

#[test]
fn runtime_requires_boot_and_exposes_active_snapshot() {
    let runtime = runtime(2, 2);
    let rejected = runtime.submit(Box::new(|| Ok(json!(null))));
    assert!(matches!(rejected, Err(RuntimeError::InvalidLifecycle(_))));
    let snapshot = runtime.boot().expect("boot");
    assert_eq!(snapshot.lifecycle.as_str(), "active");
    assert_eq!(snapshot.task_count, 0);
    assert!(matches!(
        runtime.boot(),
        Err(RuntimeError::InvalidLifecycle(_))
    ));
}

#[test]
fn gated_submission_fails_closed_without_whitelist() {
    let runtime = runtime(1, 2);
    runtime.boot().expect("boot");
    let request = capability_request();
    let gate = GateRequest::new(request.name.clone(), request.agent_id.clone());
    assert!(matches!(
        runtime.submit_gated(gate, request),
        Err(RuntimeError::GateBlocked(GateDecision::Block))
    ));
}

#[test]
fn gated_submission_runs_only_after_gate_and_authority_wiring() {
    let runtime = runtime(1, 2);
    runtime.boot().expect("boot");
    runtime.gatechain().register_tools(["read_file"]);
    runtime
        .capability_authority()
        .register_executor(|request| CapabilityResult {
            success: true,
            error: String::new(),
            capability: request.name,
            data: BTreeMap::from([("ok".to_owned(), JsonValue::Bool(true))]),
        });
    let request = capability_request();
    let mut gate = GateRequest::new(request.name.clone(), request.agent_id.clone());
    gate.interactive = true;
    let task = runtime.submit_gated(gate, request).expect("gated submit");
    let value = task.result(None).expect("capability result");
    assert_eq!(value["success"], true);
    assert_eq!(value["data"]["ok"], true);
    runtime.reap(task.handle()).expect("reap");
}

#[test]
fn runtime_executes_tracks_and_reaps_generation_safe_tasks() {
    let runtime = runtime(1, 2);
    runtime.boot().expect("boot");
    let task = runtime
        .submit(Box::new(|| Ok(json!({"value": 7}))))
        .expect("submit");
    assert_eq!(runtime.scheduler_queue_metrics().submitted, 0);
    assert_eq!(task.result(None).expect("result"), json!({"value": 7}));
    assert_eq!(task.state(), Some(RuntimeTaskState::Succeeded));
    let old_handle = task.handle();
    runtime.reap(old_handle).expect("reap");
    assert_eq!(task.state(), None);
    assert!(matches!(
        runtime.reap(old_handle),
        Err(RuntimeError::InvalidHandle)
    ));

    let reused = runtime
        .submit(Box::new(|| Ok(json!("reused"))))
        .expect("reuse slot");
    assert_eq!(reused.handle().slot(), old_handle.slot());
    assert_ne!(reused.handle().generation(), old_handle.generation());
    assert_eq!(reused.result(None).expect("reused result"), json!("reused"));
    runtime.reap(reused.handle()).expect("reap reused");
}

#[test]
fn cancellation_before_execution_marks_task_without_running_closure() {
    let runtime = runtime(2, 2);
    runtime.boot().expect("boot");
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let first = runtime
        .submit(Box::new(move || {
            started_tx.send(()).expect("worker started");
            release_rx.recv().expect("release worker");
            Ok(json!("first"))
        }))
        .expect("first submit");
    started_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("started");

    let second = runtime
        .submit(Box::new(|| Ok(json!("must not run"))))
        .expect("second submit");
    assert!(second.cancel("stopped by caller"));
    release_tx.send(()).expect("release first");
    assert_eq!(first.result(None).expect("first result"), json!("first"));
    assert_eq!(
        second.result(None),
        Err(TaskHandleError::Cancelled("stopped by caller".to_owned()))
    );
    assert_eq!(second.state(), Some(RuntimeTaskState::Cancelled));
    runtime.reap(first.handle()).expect("reap first");
    runtime.reap(second.handle()).expect("reap second");
}

#[test]
fn evicted_task_releases_direct_scheduler_state_before_reap() {
    let runtime = runtime(3, 1);
    runtime.boot().expect("boot");
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let first = runtime
        .submit(Box::new(move || {
            started_tx.send(()).expect("worker started");
            release_rx.recv().expect("release worker");
            Ok(json!("first"))
        }))
        .expect("first submit");
    started_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("started");

    let evicted = runtime
        .submit(Box::new(|| Ok(json!("evicted"))))
        .expect("queued submit");
    let accepted = runtime
        .submit(Box::new(|| Ok(json!("accepted"))))
        .expect("backpressure submit");

    assert_eq!(
        evicted.result(None),
        Err(TaskHandleError::Failed(
            "task evicted by backpressure".to_owned()
        ))
    );
    assert_eq!(evicted.state(), Some(RuntimeTaskState::Failed));
    runtime.reap(evicted.handle()).expect("reap evicted task");

    release_tx.send(()).expect("release first");
    assert_eq!(first.result(None).expect("first result"), json!("first"));
    assert_eq!(
        accepted.result(None).expect("accepted result"),
        json!("accepted")
    );
    runtime.reap(first.handle()).expect("reap first");
    runtime.reap(accepted.handle()).expect("reap accepted");
}

#[test]
fn task_deadline_is_distinct_from_observer_timeout() {
    let runtime = runtime(1, 2);
    runtime.boot().expect("boot");
    let task = runtime
        .submit_with_timeout(
            Box::new(|| {
                thread::sleep(Duration::from_millis(20));
                Ok(json!("late"))
            }),
            Duration::from_millis(5),
        )
        .expect("submit");
    assert_eq!(
        task.result(Some(Duration::from_millis(1))),
        Err(TaskHandleError::Timeout)
    );
    assert!(matches!(
        task.state(),
        Some(RuntimeTaskState::Ready | RuntimeTaskState::Running)
    ));
    assert_eq!(task.result(None), Err(TaskHandleError::TaskTimeout));
    assert_eq!(task.state(), Some(RuntimeTaskState::TimedOut));
    runtime.reap(task.handle()).expect("reap");
}

#[test]
fn panicking_task_is_failed_and_reapable() {
    let runtime = runtime(1, 2);
    runtime.boot().expect("boot");
    let task = runtime
        .submit(Box::new(|| -> Result<_, String> { panic!("boom") }))
        .expect("submit");
    assert_eq!(
        task.result(None),
        Err(TaskHandleError::Failed("task panicked".to_owned()))
    );
    assert_eq!(task.state(), Some(RuntimeTaskState::Failed));
    runtime.reap(task.handle()).expect("reap failed task");
}

#[test]
fn shutdown_drains_workers_and_rejects_new_work() {
    let runtime = runtime(2, 2);
    runtime.boot().expect("boot");
    let task = runtime
        .submit(Box::new(|| Ok(json!("done"))))
        .expect("submit");
    let snapshot = runtime
        .shutdown(Some(Duration::from_secs(1)))
        .expect("shutdown");
    assert_eq!(snapshot.lifecycle.as_str(), "halted");
    assert_eq!(task.result(None).expect("drained result"), json!("done"));
    assert!(matches!(
        runtime.submit(Box::new(|| Ok(json!(null)))),
        Err(RuntimeError::InvalidLifecycle(_))
    ));
}

#[test]
fn persistent_runtime_durably_resumes_and_recovers_unclean_root() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("fresh persistent runtime");
        assert_eq!(runtime.boot().expect("boot").lifecycle.as_str(), "active");
        runtime
            .shutdown(Some(Duration::from_secs(1)))
            .expect("clean shutdown");
    }
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("resume persistent runtime");
        runtime.boot().expect("resume boot");
    }
    {
        let recovered = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
            .expect("recover unclean root");
        assert_eq!(
            recovered.boot().expect("recovery boot").lifecycle.as_str(),
            "active"
        );
        recovered
            .shutdown(Some(Duration::from_secs(1)))
            .expect("final shutdown");
    }
    std::fs::remove_dir_all(root).expect("remove isolated test root");
}
