//! Independent tests for managed process-group coordination.

use std::collections::BTreeSet;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use l1_kernel_rs::contract::ProcessState;
use l1_kernel_rs::gatechain::{GateChain, GateDecision, GateIdentity, GateRequest};
use l1_kernel_rs::managed_process::ManagedProcessError;
use l1_kernel_rs::process_adapter::ProcessAdapterConfig;
use l1_kernel_rs::process_constraints::{
    AgentProcessMode, AgentProcessPolicy, AgentProcessSpec, AgentResourceRequest,
};
use l1_kernel_rs::process_group::{
    PROCESS_GROUP_SIGNAL_CONTRACT_VERSION, ProcessGroupError, ProcessGroupSignalError,
    ProcessGroupSignalPort, ProcessGroupSignalReport, ProcessGroupState, ReaperBudget,
};
use l1_kernel_rs::process_group_runtime::{
    GatedProcessAdmission, PROCESS_GROUP_RUNTIME_CONTRACT_VERSION, PROCESS_SPAWN_CAPABILITY,
    ProcessGroupRuntime, ProcessGroupRuntimeError,
};

fn shell_args(command: &str) -> Vec<String> {
    #[cfg(unix)]
    {
        vec!["/bin/sh".to_owned(), "-c".to_owned(), command.to_owned()]
    }
    #[cfg(windows)]
    {
        vec!["cmd.exe".to_owned(), "/C".to_owned(), command.to_owned()]
    }
}

fn runtime(max_members: usize) -> ProcessGroupRuntime {
    ProcessGroupRuntime::new(
        ProcessAdapterConfig::new(256).expect("config"),
        4,
        max_members,
        4,
        Duration::from_millis(250),
    )
    .expect("runtime")
}

fn direct_spec() -> AgentProcessSpec {
    AgentProcessSpec {
        process_id: "process-1".to_owned(),
        agent_id: "agent-1".to_owned(),
        cell_id: "cell-1".to_owned(),
        ring: 1,
        mode: AgentProcessMode::Direct,
        argv: shell_args("printf gated"),
        cwd: None,
        environment_keys: Vec::new(),
        replaces_environment: false,
        process_group_id: Some("group-1".to_owned()),
        timeout_ms: 100,
        resources: AgentResourceRequest {
            max_output_bytes: 256,
            max_cpu_time_ms: None,
            max_memory_bytes: None,
        },
    }
}

fn direct_policy(executable: &str) -> AgentProcessPolicy {
    AgentProcessPolicy {
        allowed_rings: BTreeSet::from([1]),
        allowed_terminal_ids: None,
        allowed_terminal_kinds: None,
        allowed_executables: Some(BTreeSet::from([executable.to_owned()])),
        allowed_cwd_prefixes: None,
        allowed_environment_keys: BTreeSet::new(),
        denied_environment_keys: BTreeSet::new(),
        allow_environment_replacement: false,
        max_argv_items: 8,
        max_timeout_ms: 1_000,
        max_output_bytes: 1_024,
        max_cpu_time_ms: None,
        max_memory_bytes: None,
        allow_shell: false,
        require_interactive_terminal: false,
        require_pty: false,
        require_process_group: true,
    }
}

fn process_gate() -> GateRequest {
    let mut gate = GateRequest::new(PROCESS_SPAWN_CAPABILITY, "agent-1");
    gate.identity = Some(GateIdentity {
        pid: 41,
        ring: 1,
        state: ProcessState::Running,
        verified: true,
    });
    gate
}

fn drain(runtime: &ProcessGroupRuntime, group: l1_kernel_rs::process_group::ProcessGroupId) {
    let budget = ReaperBudget::new(1, 8).expect("budget");
    for _ in 0..200 {
        runtime.sweep(budget);
        if runtime
            .snapshot(group)
            .expect("snapshot")
            .members
            .is_empty()
        {
            return;
        }
        thread::sleep(Duration::from_millis(1));
    }
    panic!("group did not drain: {:?}", runtime.snapshot(group));
}

#[derive(Default)]
struct RecordingSignalPort {
    plans: Mutex<Vec<l1_kernel_rs::process_group::ProcessGroupTerminationPlan>>,
    delivered: u64,
    wrong_group: bool,
}

impl ProcessGroupSignalPort for RecordingSignalPort {
    fn send_stop(
        &self,
        plan: &l1_kernel_rs::process_group::ProcessGroupTerminationPlan,
    ) -> Result<ProcessGroupSignalReport, String> {
        self.plans.lock().expect("plans lock").push(plan.clone());
        Ok(ProcessGroupSignalReport {
            contract_version: PROCESS_GROUP_SIGNAL_CONTRACT_VERSION,
            group_id: if self.wrong_group {
                plan.group_id + 1
            } else {
                plan.group_id
            },
            generation: plan.generation,
            attempted: plan.handles.len() as u64,
            delivered: self.delivered.min(plan.handles.len() as u64),
        })
    }
}

#[test]
fn contract_and_normal_exit_reconcile_both_books() {
    assert_eq!(PROCESS_GROUP_RUNTIME_CONTRACT_VERSION, 1);
    let runtime = runtime(2);
    let group = runtime.create_group("normal", None).expect("group");
    let handle = runtime
        .spawn_args(group, &shell_args("exit 7"), None)
        .expect("child");
    runtime.request_stop(group, "test stop").expect("stop");
    drain(&runtime, group);
    let snapshot = runtime.snapshot(group).expect("snapshot");
    assert_eq!(snapshot.state, ProcessGroupState::Stopped);
    assert!(snapshot.members.is_empty());
    assert_eq!(runtime.processes().active_count(), 0);
    assert!(handle.raw() > 0);
}

#[test]
fn bounded_sweep_never_exceeds_member_budget() {
    let runtime = runtime(2);
    let group = runtime.create_group("bounded", None).expect("group");
    runtime
        .spawn_args(group, &shell_args("sleep 0.05"), None)
        .expect("first");
    runtime
        .spawn_args(group, &shell_args("sleep 0.05"), None)
        .expect("second");
    runtime.request_stop(group, "bounded stop").expect("stop");
    let report = runtime.sweep(ReaperBudget::new(1, 1).expect("budget"));
    assert_eq!(report.groups_inspected, 1);
    assert!(report.members_inspected <= 1);
    drain(&runtime, group);
}

#[test]
fn explicit_timeout_mode_cancels_a_live_child() {
    let runtime = runtime(1);
    let group = runtime.create_group("cancel", None).expect("group");
    runtime
        .spawn_args(group, &shell_args("sleep 5"), None)
        .expect("child");
    runtime.request_stop(group, "cancel").expect("stop");
    let report = runtime.sweep_with_timeout(
        ReaperBudget::new(1, 1).expect("budget"),
        Duration::from_millis(250),
    );
    assert_eq!(report.reaped, 1);
    let snapshot = runtime.snapshot(group).expect("snapshot");
    assert_eq!(snapshot.state, ProcessGroupState::Stopped);
    assert!(snapshot.members.is_empty());
    assert_eq!(runtime.processes().active_count(), 0);
}

#[test]
fn failed_group_admission_cleans_up_spawned_child() {
    let runtime = runtime(1);
    let group = runtime.create_group("capacity", Some(1)).expect("group");
    runtime
        .spawn_args(group, &shell_args("sleep 0.2"), None)
        .expect("first");
    let error = runtime
        .spawn_args(group, &shell_args("printf rejected"), None)
        .expect_err("capacity");
    assert_eq!(
        error,
        ProcessGroupRuntimeError::Group(ProcessGroupError::Capacity)
    );
    assert_eq!(runtime.processes().active_count(), 1);
    assert_eq!(runtime.snapshot(group).expect("snapshot").members.len(), 1);
    runtime.request_stop(group, "cleanup").expect("stop");
    drain(&runtime, group);
}

#[test]
fn unknown_process_handle_is_not_reused_by_group_book() {
    let runtime = runtime(1);
    let group = runtime.create_group("unknown", None).expect("group");
    let error = runtime
        .spawn_args(group, &["praxis-missing-runtime".to_owned()], None)
        .expect_err("missing executable");
    assert!(matches!(
        error,
        ProcessGroupRuntimeError::Process(ManagedProcessError::NotFound(_))
    ));
    assert_eq!(runtime.snapshot(group).expect("snapshot").members.len(), 0);
}

#[test]
fn gated_constraint_admission_blocks_before_process_spawn() {
    let runtime = runtime(1);
    let group = runtime.create_group("gated-block", None).expect("group");
    let gatechain = GateChain::new();
    let spec = direct_spec();
    let error = runtime
        .spawn_gated_constrained(
            group,
            GatedProcessAdmission {
                gatechain: &gatechain,
                gate: &process_gate(),
                spec: &spec,
                policy: direct_policy(spec.executable().expect("executable")),
                terminal: None,
                options: None,
            },
        )
        .expect_err("empty whitelist must block");
    assert_eq!(
        error,
        ProcessGroupRuntimeError::GateBlocked(GateDecision::Block)
    );
    assert_eq!(runtime.processes().active_count(), 0);
    assert_eq!(gatechain.ledger().len(), 1);
}

#[test]
fn gated_constraint_admission_authorizes_then_reaps_process() {
    let runtime = runtime(1);
    let group = runtime.create_group("gated-pass", None).expect("group");
    let gatechain = GateChain::new();
    gatechain.register_tools([PROCESS_SPAWN_CAPABILITY]);
    let spec = direct_spec();
    let handle = runtime
        .spawn_gated_constrained(
            group,
            GatedProcessAdmission {
                gatechain: &gatechain,
                gate: &process_gate(),
                spec: &spec,
                policy: direct_policy(spec.executable().expect("executable")),
                terminal: None,
                options: None,
            },
        )
        .expect("authorized spawn");
    runtime.request_stop(group, "test stop").expect("stop");
    drain(&runtime, group);
    assert_eq!(runtime.processes().active_count(), 0);
    assert!(handle.raw() > 0);
    assert_eq!(gatechain.ledger().len(), 1);
}

#[test]
fn gated_constraint_admission_rejects_capability_or_identity_mismatch() {
    let runtime = runtime(1);
    let group = runtime
        .create_group("gated-correlation", None)
        .expect("group");
    let gatechain = GateChain::new();
    gatechain.register_tools([PROCESS_SPAWN_CAPABILITY]);
    let spec = direct_spec();
    let mut gate = process_gate();
    gate.tool = "other.capability".to_owned();
    let error = runtime
        .spawn_gated_constrained(
            group,
            GatedProcessAdmission {
                gatechain: &gatechain,
                gate: &gate,
                spec: &spec,
                policy: direct_policy(spec.executable().expect("executable")),
                terminal: None,
                options: None,
            },
        )
        .expect_err("wrong capability must block");
    assert_eq!(
        error,
        ProcessGroupRuntimeError::GateBlocked(GateDecision::Block)
    );
    assert_eq!(runtime.processes().active_count(), 0);
    assert!(gatechain.ledger().is_empty());
}

#[test]
fn drain_once_requests_all_groups_and_respects_sweep_budget() {
    let runtime = runtime(2);
    let first = runtime
        .create_group("drain-first", None)
        .expect("first group");
    let second = runtime
        .create_group("drain-second", None)
        .expect("second group");
    runtime
        .spawn_args(first, &shell_args("sleep 0.02"), None)
        .expect("first child");
    runtime
        .spawn_args(second, &shell_args("sleep 0.02"), None)
        .expect("second child");

    let first_report = runtime
        .drain_once(
            "bounded shutdown",
            ReaperBudget::new(1, 1).expect("budget"),
            Duration::ZERO,
        )
        .expect("drain");
    assert_eq!(first_report.groups_requested, 2);
    assert!(first_report.members_inspected <= 1);
    assert!(!first_report.complete);

    let mut report = first_report;
    for _ in 0..200 {
        if report.complete {
            break;
        }
        thread::sleep(Duration::from_millis(1));
        report = runtime
            .drain_once(
                "bounded shutdown",
                ReaperBudget::new(2, 2).expect("budget"),
                Duration::from_millis(250),
            )
            .expect("drain");
    }
    assert!(report.complete, "groups did not drain: {report:?}");
    assert_eq!(runtime.processes().active_count(), 0);
}

#[test]
fn host_signal_report_is_generation_bound_before_reaping() {
    let runtime = runtime(1);
    let group = runtime.create_group("signal", None).expect("group");
    runtime
        .spawn_args(group, &shell_args("sleep 5"), None)
        .expect("child");
    let port = RecordingSignalPort {
        delivered: 1,
        ..RecordingSignalPort::default()
    };
    let report = runtime
        .request_stop_with_signal(group, "signal stop", &port)
        .expect("signal report");
    assert_eq!(report.attempted, 1);
    assert_eq!(report.delivered, 1);
    assert_eq!(port.plans.lock().expect("plans lock").len(), 1);
    let sweep = runtime.sweep_with_timeout(
        ReaperBudget::new(1, 1).expect("budget"),
        Duration::from_millis(250),
    );
    assert_eq!(sweep.reaped, 1);
}

#[test]
fn mismatched_host_signal_report_fails_closed_and_keeps_group_owned() {
    let runtime = runtime(1);
    let group = runtime
        .create_group("signal-mismatch", None)
        .expect("group");
    runtime
        .spawn_args(group, &shell_args("sleep 0.02"), None)
        .expect("child");
    let port = RecordingSignalPort {
        wrong_group: true,
        ..RecordingSignalPort::default()
    };
    assert_eq!(
        runtime.request_stop_with_signal(group, "bad report", &port),
        Err(ProcessGroupRuntimeError::Signal(
            ProcessGroupSignalError::InvalidReport("group_id")
        ))
    );
    assert_eq!(
        runtime.snapshot(group).expect("snapshot").state,
        ProcessGroupState::Draining
    );
    drain(&runtime, group);
}
