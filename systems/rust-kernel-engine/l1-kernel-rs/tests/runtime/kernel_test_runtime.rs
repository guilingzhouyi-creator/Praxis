//! Independent execution-host tests for the Rust kernel runtime candidate.

use std::collections::BTreeMap;
use std::sync::{Arc, Barrier, mpsc};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use l1_kernel_rs::agent_loop::{AgentLoopSpec, AgentLoopState};
use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::contract::{CapabilityRequest, CapabilityResult, JsonObject, JsonValue};
use l1_kernel_rs::gatechain::{GateDecision, GateRequest};
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::recovery::RecoveryAction;
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig, RuntimeError, RuntimeTaskState};
use l1_kernel_rs::session::{SessionSpec, SessionState};
use l1_kernel_rs::terminal::{TerminalSpec, TerminalState};
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

fn concurrent_runtime() -> Arc<KernelRuntime> {
    Arc::new(
        KernelRuntime::new(
            spec("state"),
            RuntimeConfig::new(8, 4, WorkerConfig::new(4, 4, 4, Duration::from_millis(20))),
        )
        .expect("valid concurrent runtime"),
    )
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
    let rows = runtime.capability_authority().audit().query(10, None);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].op, "capability.gate");
    assert!(!rows[0].success);
    assert!(rows[0].error.contains("BLOCK"));
}

#[test]
fn gated_submission_identity_mismatch_is_audited_before_worker_admission() {
    let runtime = runtime(1, 2);
    runtime.boot().expect("boot");
    let request = capability_request();
    let mut gate = GateRequest::new(request.name.clone(), request.agent_id.clone());
    gate.agent_id = "forged-agent".to_owned();
    assert!(matches!(
        runtime.submit_gated(gate, request),
        Err(RuntimeError::GateBlocked(GateDecision::Block))
    ));
    assert_eq!(runtime.snapshot().task_count, 0);
    let rows = runtime.capability_authority().audit().query(10, None);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].op, "capability.gate_mismatch");
    assert!(!rows[0].success);
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
fn runtime_batch_preserves_ordered_results_and_reaps_every_handle() {
    let runtime = runtime(4, 4);
    runtime.boot().expect("boot");
    let tasks = runtime
        .submit_batch(
            (0_u64..4)
                .map(|value| Box::new(move || Ok(json!(value))) as l1_kernel_rs::worker::TaskFn)
                .collect(),
        )
        .expect("batch submit");
    assert_eq!(tasks.len(), 4);
    for (value, task) in (0_u64..4).zip(tasks) {
        assert_eq!(task.result(None).expect("batch result"), json!(value));
        assert_eq!(task.state(), Some(RuntimeTaskState::Succeeded));
        runtime.reap(task.handle()).expect("batch reap");
    }
    let snapshot = runtime.snapshot();
    assert_eq!(snapshot.task_count, 0);
    assert_eq!(snapshot.terminal_tasks, 0);
}

#[test]
fn runtime_batch_capacity_failure_rolls_back_all_reserved_tasks() {
    let runtime = runtime(2, 2);
    runtime.boot().expect("boot");
    assert!(
        runtime
            .submit_batch(
                (0..3)
                    .map(|_| { Box::new(|| Ok(json!(null))) as l1_kernel_rs::worker::TaskFn })
                    .collect(),
            )
            .is_err()
    );
    assert_eq!(runtime.snapshot().task_count, 0);
    let task = runtime
        .submit(Box::new(|| Ok(json!("reused after rollback"))))
        .expect("submit after rollback");
    assert_eq!(
        task.result(None).expect("result after rollback"),
        json!("reused after rollback")
    );
    runtime.reap(task.handle()).expect("reap after rollback");
}

#[test]
fn immediate_tasks_retain_terminal_state_before_submit_returns() {
    let runtime = runtime(1, 1);
    runtime.boot().expect("boot");
    for _ in 0..128 {
        let task = runtime
            .submit(Box::new(|| Ok(json!("immediate"))))
            .expect("submit immediate task");
        assert_eq!(
            task.result(None).expect("immediate result"),
            json!("immediate")
        );
        assert_eq!(task.state(), Some(RuntimeTaskState::Succeeded));
        runtime.reap(task.handle()).expect("reap immediate task");
    }
    assert_eq!(runtime.snapshot().task_count, 0);
}

#[test]
fn runtime_reap_finished_is_bounded_and_leaves_live_tasks_owned() {
    let runtime = concurrent_runtime();
    runtime.boot().expect("boot");
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let live = runtime
        .submit(Box::new(move || {
            started_tx.send(()).expect("worker started");
            release_rx.recv().expect("release worker");
            Ok(json!("live"))
        }))
        .expect("submit live task");
    started_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("started");
    let finished = runtime
        .submit_batch(
            (0_u64..3)
                .map(|value| Box::new(move || Ok(json!(value))) as l1_kernel_rs::worker::TaskFn)
                .collect(),
        )
        .expect("submit finished tasks");
    for task in &finished {
        assert!(task.result(None).is_ok());
    }

    let pending = runtime.reap_finished(1).expect("bounded pending sweep");
    assert_eq!(pending.inspected, 1);
    assert_eq!(pending.pending, 1);
    assert_eq!(pending.reaped, 0);

    let first = runtime.reap_finished(2).expect("bounded terminal sweep");
    assert_eq!(first.inspected, 2);
    assert!(first.reaped >= 1);
    assert_eq!(first.reaped + first.pending, 2);
    assert_eq!(first.errors, 0);

    release_tx.send(()).expect("release worker");
    assert_eq!(live.result(None).expect("live result"), json!("live"));
    runtime.reap(live.handle()).expect("reap live task");
    let last = runtime.reap_finished(4).expect("remaining terminal sweep");
    assert!(last.reaped >= 1);
    assert_eq!(runtime.snapshot().task_count, 0);
    assert!(matches!(
        runtime.reap_finished(0),
        Err(RuntimeError::InvalidReapBudget)
    ));
}

#[test]
fn observed_admission_keeps_parallel_task_accounting_complete() {
    let runtime = concurrent_runtime();
    runtime.boot().expect("boot");
    runtime.reset_observed_lock_wait();
    let start = Arc::new(Barrier::new(5));
    let mut workers = Vec::new();
    for _ in 0..4 {
        let runtime = Arc::clone(&runtime);
        let start = Arc::clone(&start);
        workers.push(thread::spawn(move || {
            start.wait();
            for _ in 0..32 {
                let task = runtime
                    .submit_observed(Box::new(|| Ok(json!(null))))
                    .expect("parallel submit");
                assert_eq!(task.result(None).expect("parallel result"), json!(null));
                assert_eq!(task.state(), Some(RuntimeTaskState::Succeeded));
                runtime.reap(task.handle()).expect("parallel reap");
            }
        }));
    }
    start.wait();
    for worker in workers {
        worker.join().expect("parallel worker");
    }
    let snapshot = runtime.snapshot();
    assert_eq!(snapshot.task_count, 0);
    assert_eq!(snapshot.terminal_tasks, 0);
    let wait = runtime.observed_lock_wait();
    assert_eq!(
        wait.total_ns(),
        wait.admission_wait_ns + wait.task_book_wait_ns
    );
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
fn shutdown_publishes_draining_before_waiting_for_admission_barrier() {
    let runtime = Arc::new(runtime(2, 2));
    runtime.boot().expect("boot");
    let (started_tx, started_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let task = runtime
        .submit(Box::new(move || {
            started_tx.send(()).expect("worker started");
            release_rx.recv().expect("release worker");
            Ok(json!("drained"))
        }))
        .expect("submit blocker");
    started_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("blocker started");

    let shutdown_runtime = Arc::clone(&runtime);
    let shutdown = thread::spawn(move || shutdown_runtime.shutdown(Some(Duration::from_secs(1))));
    for _ in 0..100 {
        if runtime.snapshot().lifecycle.as_str() == "draining" {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(runtime.snapshot().lifecycle.as_str(), "draining");
    assert!(matches!(
        runtime.submit(Box::new(|| Ok(json!(null)))),
        Err(RuntimeError::InvalidLifecycle(_))
    ));

    release_tx.send(()).expect("release blocker");
    assert_eq!(
        shutdown
            .join()
            .expect("shutdown thread")
            .expect("shutdown succeeds")
            .lifecycle
            .as_str(),
        "halted"
    );
    assert_eq!(task.result(None).expect("drained task"), json!("drained"));
    runtime.reap(task.handle()).expect("reap drained task");
}

#[test]
fn persistent_runtime_durably_resumes_and_recovers_unclean_root() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("fresh persistent runtime");
        assert_eq!(
            runtime.recovery_decision().expect("fresh decision").action,
            RecoveryAction::Fresh
        );
        assert_eq!(runtime.boot().expect("boot").lifecycle.as_str(), "active");
        runtime
            .shutdown(Some(Duration::from_secs(1)))
            .expect("clean shutdown");
        assert_eq!(
            runtime
                .recovery_decision()
                .expect("post-shutdown decision")
                .action,
            RecoveryAction::ResumeClean
        );
    }
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("resume persistent runtime");
        let decision = runtime.recovery_decision().expect("clean decision");
        assert_eq!(decision.action, RecoveryAction::ResumeClean);
        assert_eq!(decision.generation, 1);
        runtime.boot().expect("resume boot");
    }
    {
        let recovered = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
            .expect("recover unclean root");
        assert!(matches!(
            recovered.boot(),
            Err(RuntimeError::RecoveryRequired(RecoveryAction::Reject))
        ));
        recovered
            .checkpoint_execution(false)
            .expect("write explicit recovery checkpoint");
        let decision = recovered.recovery_decision().expect("recovery decision");
        assert_eq!(decision.action, RecoveryAction::RecoverUnclean);
        recovered
            .acknowledge_recovery(&decision)
            .expect("acknowledge recovery");
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

#[test]
fn persistent_runtime_owns_rust_configuration_root() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    let runtime = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
        .expect("persistent runtime");
    let (config_document, settings_document) =
        runtime.config_documents().expect("configuration documents");
    assert_eq!(config_document.revision, 0);
    assert_eq!(settings_document.revision, 0);
    assert!(root.join("config/manifest.json").is_file());
    assert!(root.join("config/config.json").is_file());
    assert!(root.join("config/settings.json").is_file());
    std::fs::remove_dir_all(root).expect("remove isolated config root");
}

#[test]
fn persistent_runtime_rejects_foreign_configuration_root() {
    let root = temp_root();
    let config_root = temp_root();
    std::fs::create_dir_all(&config_root).expect("foreign config root");
    std::fs::write(config_root.join("python-settings.json"), b"{}").expect("foreign config");
    let result = KernelRuntime::open_persistent(
        spec(root.to_string_lossy().to_string())
            .with_config_root(config_root.to_string_lossy().to_string()),
        config(2, 2),
        &root,
    );
    assert!(matches!(result, Err(RuntimeError::ConfigStore(_))));
    std::fs::remove_dir_all(root).expect("remove state root");
    std::fs::remove_dir_all(config_root).expect("remove foreign config root");
}

#[test]
fn runtime_configuration_owner_persists_mutations_for_reopen() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
        .expect("persistent runtime");
    let config_document = runtime
        .set_config("scheduler.max_workers", json!(4))
        .expect("config mutation");
    assert_eq!(config_document.revision, 1);
    assert_eq!(config_document.values["scheduler.max_workers"], json!(4));
    let settings_document = runtime
        .set_setting("terminal.preferred", json!("bash"))
        .expect("setting mutation");
    assert_eq!(settings_document.revision, 1);
    let (paired_config, paired_settings) = runtime
        .set_config_and_setting(
            "scheduler.max_processes",
            json!(16),
            "terminal.color",
            json!(true),
        )
        .expect("paired mutation");
    assert_eq!(paired_config.revision, 2);
    assert_eq!(paired_settings.revision, 2);
    drop(runtime);

    let reopened = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
        .expect("reopen runtime");
    let (config_document, settings_document) = reopened
        .config_documents()
        .expect("configuration documents");
    assert_eq!(config_document.values["scheduler.max_workers"], json!(4));
    assert_eq!(config_document.values["scheduler.max_processes"], json!(16));
    assert_eq!(
        settings_document.values["terminal.preferred"],
        json!("bash")
    );
    assert_eq!(settings_document.values["terminal.color"], json!(true));
    assert_eq!(config_document.revision, 2);
    assert_eq!(settings_document.revision, 2);
    std::fs::remove_dir_all(root).expect("remove runtime root");
}

#[test]
fn nonpersistent_runtime_has_no_configuration_owner() {
    let runtime = KernelRuntime::new(spec("nonpersistent-runtime"), config(2, 2))
        .expect("nonpersistent runtime");
    assert!(matches!(
        runtime.config_documents(),
        Err(RuntimeError::ConfigStore(message)) if message == "runtime is not persistent"
    ));
    assert!(matches!(
        runtime.set_config("scheduler.max_workers", json!(4)),
        Err(RuntimeError::ConfigStore(message)) if message == "runtime is not persistent"
    ));
}

#[test]
fn runtime_configuration_pair_failure_preserves_both_documents() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    let runtime = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
        .expect("persistent runtime");
    let before = runtime.config_documents().expect("configuration documents");
    let config_path = root.join("config/config.json");
    let settings_path = root.join("config/settings.json");
    let before_config_bytes = std::fs::read(&config_path).expect("config bytes");
    std::fs::remove_file(&settings_path).expect("remove settings file");
    std::fs::create_dir(&settings_path).expect("block settings replacement");

    assert!(matches!(
        runtime.set_config_and_setting(
            "scheduler.max_workers",
            json!(8),
            "terminal.preferred",
            json!("bash"),
        ),
        Err(RuntimeError::ConfigStore(_))
    ));
    assert_eq!(
        runtime.config_documents().expect("configuration documents"),
        before
    );
    assert_eq!(
        std::fs::read(&config_path).expect("rolled-back config bytes"),
        before_config_bytes
    );
    assert_eq!(
        std::fs::read_dir(root.join("config"))
            .expect("config entries")
            .filter_map(Result::ok)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".config.json.tmp-")
            })
            .count(),
        0,
        "runtime pair failure must clean staged config files"
    );
    std::fs::remove_dir(&settings_path).expect("remove settings blocker");
    std::fs::remove_dir_all(root).expect("remove runtime root");
}

#[test]
fn persistent_runtime_owns_and_restores_execution_books() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("fresh persistent runtime");
        runtime.boot().expect("boot");
        let session = runtime
            .sessions()
            .create(SessionSpec::new(
                "session-owned",
                "agent-a",
                "cell-a",
                "worker",
                8,
            ))
            .expect("session");
        session.activate().expect("activate session");
        session.close(true).expect("close session");
        runtime
            .terminals()
            .register(TerminalSpec::new("terminal-owned", 4, 4))
            .expect("terminal");
        runtime
            .agent_loops()
            .register(AgentLoopSpec::new(
                "loop-owned",
                "agent-a",
                "cell-a",
                "session-owned",
                "terminal-owned",
            ))
            .expect("loop");
        let snapshot = runtime
            .shutdown(Some(Duration::from_secs(1)))
            .expect("clean shutdown checkpoints execution books");
        assert_eq!(snapshot.lifecycle.as_str(), "halted");
    }
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
            .expect("reopen persistent runtime");
        assert_eq!(
            runtime
                .sessions()
                .get("session-owned")
                .expect("session")
                .state(),
            SessionState::Closed
        );
        assert_eq!(
            runtime
                .terminals()
                .snapshot("terminal-owned")
                .expect("terminal")
                .state,
            TerminalState::Created
        );
        assert_eq!(
            runtime
                .agent_loops()
                .snapshot("loop-owned")
                .expect("loop")
                .state,
            AgentLoopState::Created
        );
    }
    std::fs::remove_dir_all(root).expect("remove isolated test root");
}

#[test]
fn explicit_unclean_execution_checkpoint_restores_recovery_states() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("fresh persistent runtime");
        runtime.boot().expect("boot");
        runtime
            .sessions()
            .create(SessionSpec::new(
                "session-crash",
                "agent-a",
                "cell-a",
                "worker",
                8,
            ))
            .expect("session");
        let document = runtime
            .checkpoint_execution(false)
            .expect("unclean execution checkpoint");
        assert!(!document.clean_shutdown);
    }
    let runtime = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
        .expect("recover persistent runtime");
    let decision = runtime.recovery_decision().expect("recovery decision");
    assert_eq!(decision.action, RecoveryAction::RecoverUnclean);
    assert!(matches!(
        runtime.boot(),
        Err(RuntimeError::RecoveryRequired(
            RecoveryAction::RecoverUnclean
        ))
    ));
    runtime
        .acknowledge_recovery(&decision)
        .expect("acknowledge recovery");
    assert_eq!(
        runtime
            .sessions()
            .get("session-crash")
            .expect("session")
            .state(),
        SessionState::Crashed
    );
    std::fs::remove_dir_all(root).expect("remove isolated test root");
}

#[test]
fn rejected_clean_shutdown_preserves_unclean_execution_checkpoint() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("fresh persistent runtime");
        runtime.boot().expect("boot");
        let session = runtime
            .sessions()
            .create(SessionSpec::new(
                "session-open",
                "agent-a",
                "cell-a",
                "worker",
                8,
            ))
            .expect("active session");
        session.activate().expect("activate session");
        let result = runtime.shutdown(Some(Duration::from_secs(1)));
        assert!(
            matches!(result, Err(RuntimeError::ExecutionStore(_))),
            "{result:?}"
        );
    }
    {
        let recovered = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
            .expect("recover after rejected clean shutdown");
        assert_eq!(
            recovered
                .recovery_decision()
                .expect("unclean decision")
                .action,
            RecoveryAction::RecoverUnclean
        );
        assert_eq!(
            recovered
                .sessions()
                .get("session-open")
                .expect("session")
                .state(),
            SessionState::Crashed
        );
    }
    std::fs::remove_dir_all(root).expect("remove isolated test root");
}

#[test]
fn rejected_state_shutdown_demotes_clean_execution_checkpoint() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("fresh persistent runtime");
        runtime.boot().expect("boot");
        let checkpoint = root.join("runtime/checkpoint.json");
        std::fs::remove_file(&checkpoint).expect("remove state checkpoint");
        std::fs::create_dir(&checkpoint).expect("block state checkpoint replacement");

        assert!(matches!(
            runtime.shutdown(Some(Duration::from_secs(1))),
            Err(RuntimeError::StateStore(_))
        ));
        std::fs::remove_dir(&checkpoint).expect("remove state checkpoint blocker");
    }
    let recovered = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
        .expect("recover after rejected state shutdown");
    assert_eq!(
        recovered
            .recovery_decision()
            .expect("unclean decision")
            .action,
        RecoveryAction::RecoverUnclean
    );
    std::fs::remove_dir_all(root).expect("remove isolated test root");
}

#[test]
fn recovery_acknowledgement_rejects_stale_decisions() {
    let root = temp_root();
    let root_text = root.to_string_lossy().to_string();
    {
        let runtime = KernelRuntime::open_persistent(spec(root_text.clone()), config(2, 2), &root)
            .expect("fresh persistent runtime");
        runtime.boot().expect("boot");
        runtime
            .checkpoint_execution(false)
            .expect("unclean checkpoint");
    }
    let runtime = KernelRuntime::open_persistent(spec(root_text), config(2, 2), &root)
        .expect("recover persistent runtime");
    let mut stale = runtime.recovery_decision().expect("decision");
    stale.generation = stale.generation.saturating_sub(1);
    assert_eq!(
        runtime.acknowledge_recovery(&stale),
        Err(RuntimeError::RecoveryDecisionStale)
    );
    let decision = runtime.recovery_decision().expect("current decision");
    runtime
        .acknowledge_recovery(&decision)
        .expect("acknowledge current decision");
    assert!(matches!(
        runtime.acknowledge_recovery(&decision),
        Err(RuntimeError::RecoveryDecisionStale)
    ));
    std::fs::remove_dir_all(root).expect("remove root");
}

#[test]
fn nonpersistent_runtime_cannot_claim_execution_checkpoint_ownership() {
    let runtime = runtime(1, 1);
    assert!(matches!(
        runtime.checkpoint_execution(false),
        Err(RuntimeError::ExecutionStore(_))
    ));
}
