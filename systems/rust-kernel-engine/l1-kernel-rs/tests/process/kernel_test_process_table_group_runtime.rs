//! Independent tests for ProcessTable-authoritative process groups.

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use l1_kernel_rs::audit::AuditLog;
use l1_kernel_rs::gatechain::{GateIdentity, GateRequest};
use l1_kernel_rs::process::{ProcessState, ProcessTable, ProcessTableConfig};
use l1_kernel_rs::process_adapter::ProcessAdapterConfig;
use l1_kernel_rs::process_constraints::{
    AgentProcessMode, AgentProcessPolicy, AgentProcessSpec, AgentResourceRequest,
};
use l1_kernel_rs::process_group::{
    PROCESS_GROUP_SIGNAL_CONTRACT_VERSION, ProcessGroupSignalPort, ProcessGroupSignalReport,
    ProcessGroupState, ReaperBudget,
};
use l1_kernel_rs::process_group_runtime::{GatedProcessAdmission, PROCESS_SPAWN_CAPABILITY};
use l1_kernel_rs::process_table_group_runtime::{
    PROCESS_TABLE_GROUP_RUNTIME_CONTRACT_VERSION, ProcessTableGroupRuntime,
    ProcessTableGroupRuntimeError,
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

fn table() -> Arc<ProcessTable> {
    Arc::new(ProcessTable::new(ProcessTableConfig::new(
        64, "init", "kernel", 0, 1,
    )))
}

fn runtime(table: Arc<ProcessTable>, max_members: usize) -> ProcessTableGroupRuntime {
    ProcessTableGroupRuntime::new(
        ProcessAdapterConfig::new(256).expect("config"),
        4,
        max_members,
        4,
        Duration::from_millis(250),
        table,
    )
    .expect("runtime")
}

fn runtime_with_audit(
    table: Arc<ProcessTable>,
    max_members: usize,
    audit: Arc<AuditLog>,
) -> ProcessTableGroupRuntime {
    ProcessTableGroupRuntime::new_with_audit(
        ProcessAdapterConfig::new(256).expect("config"),
        4,
        max_members,
        4,
        Duration::from_millis(250),
        table,
        audit,
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

fn drain(runtime: &ProcessTableGroupRuntime, group: l1_kernel_rs::process_group::ProcessGroupId) {
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
    targets: Mutex<Vec<u64>>,
}

impl ProcessGroupSignalPort for RecordingSignalPort {
    fn send_stop(
        &self,
        plan: &l1_kernel_rs::process_group::ProcessGroupTerminationPlan,
    ) -> Result<ProcessGroupSignalReport, String> {
        self.targets
            .lock()
            .expect("targets lock")
            .extend(plan.handles.iter().copied());
        Ok(ProcessGroupSignalReport {
            contract_version: PROCESS_GROUP_SIGNAL_CONTRACT_VERSION,
            group_id: plan.group_id,
            generation: plan.generation,
            attempted: plan.handles.len() as u64,
            delivered: plan.handles.len() as u64,
        })
    }
}

#[test]
fn process_table_is_the_only_child_identity_and_both_books_reap() {
    assert_eq!(PROCESS_TABLE_GROUP_RUNTIME_CONTRACT_VERSION, 1);
    let table = table();
    let runtime = runtime(Arc::clone(&table), 2);
    let group = runtime
        .create_group("table-authority", None)
        .expect("group");
    let handle = runtime
        .spawn_args(group, &shell_args("exit 7"), None)
        .expect("child");
    assert_eq!(
        table.get_by_handle(handle).expect("table row").state,
        ProcessState::Running
    );
    runtime.request_stop(group, "test stop").expect("stop");
    drain(&runtime, group);
    assert_eq!(
        runtime.snapshot(group).expect("snapshot").state,
        ProcessGroupState::Stopped
    );
    assert!(table.get_by_handle(handle).is_none());
    assert_eq!(table.list_processes(None).len(), 1);
}

#[test]
fn bridge_snapshot_supplies_host_mapping_without_exposing_child_objects() {
    let table = table();
    let runtime = runtime(Arc::clone(&table), 1);
    let group = runtime.create_group("mapping", None).expect("group");
    let handle = runtime
        .spawn_args(group, &shell_args("sleep 0.02"), None)
        .expect("child");
    let snapshot = runtime.bridge().snapshot(handle).expect("bridge snapshot");
    assert_eq!(snapshot.handle, handle.raw());
    assert!(snapshot.pid > 0);
    runtime.request_stop(group, "cleanup").expect("stop");
    drain(&runtime, group);
}

#[test]
fn host_signal_report_is_validated_before_table_reap() {
    let table = table();
    let audit = Arc::new(AuditLog::with_capacity(16));
    let runtime = runtime_with_audit(Arc::clone(&table), 1, Arc::clone(&audit));
    let group = runtime.create_group("signal", None).expect("group");
    let handle = runtime
        .spawn_args(group, &shell_args("exit 0"), None)
        .expect("child");
    let port = RecordingSignalPort::default();
    let report = runtime
        .request_stop_with_signal(group, "signal stop", &port)
        .expect("signal report");
    assert_eq!(report.delivered, 1);
    assert_eq!(
        *port.targets.lock().expect("targets lock"),
        vec![handle.raw()]
    );
    assert!(
        audit
            .query(16, None)
            .iter()
            .any(|row| row.op == "process.group.signal" && row.success)
    );
    drain(&runtime, group);
    assert!(table.get_by_handle(handle).is_none());
}

#[test]
fn group_capacity_rollback_reaps_process_table_row() {
    let table = table();
    let runtime = runtime(Arc::clone(&table), 1);
    let group = runtime.create_group("capacity", Some(1)).expect("group");
    runtime
        .spawn_args(group, &shell_args("sleep 0.2"), None)
        .expect("first");
    let error = runtime
        .spawn_args(group, &shell_args("printf rejected"), None)
        .expect_err("capacity");
    assert!(matches!(error, ProcessTableGroupRuntimeError::Group(_)));
    assert_eq!(table.list_processes(None).len(), 2);
    runtime.request_stop(group, "cleanup").expect("stop");
    drain(&runtime, group);
    assert_eq!(table.list_processes(None).len(), 1);
}

#[test]
fn gated_process_table_path_blocks_before_spawn_and_records_gate() {
    let table = table();
    let runtime = runtime(Arc::clone(&table), 1);
    let group = runtime.create_group("gated-block", None).expect("group");
    let gatechain = l1_kernel_rs::gatechain::GateChain::new();
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
    assert!(matches!(
        error,
        ProcessTableGroupRuntimeError::GateBlocked(_)
    ));
    assert_eq!(runtime.bridge().active_count(), 0);
    assert_eq!(table.list_processes(None).len(), 1);
    assert_eq!(gatechain.ledger().len(), 1);
}

#[test]
fn gated_process_table_path_joins_and_reaps_after_authorization() {
    let table = table();
    let runtime = runtime(Arc::clone(&table), 1);
    let group = runtime.create_group("gated-pass", None).expect("group");
    let gatechain = l1_kernel_rs::gatechain::GateChain::new();
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
    runtime.request_stop(group, "gated cleanup").expect("stop");
    drain(&runtime, group);
    assert!(table.get_by_handle(handle).is_none());
    assert_eq!(gatechain.ledger().len(), 1);
}

#[test]
fn process_table_group_admission_records_bounded_audit_evidence() {
    let table = table();
    let audit = Arc::new(AuditLog::with_capacity(16));
    let runtime = runtime_with_audit(Arc::clone(&table), 1, Arc::clone(&audit));
    let group = runtime.create_group("audited", None).expect("group");
    let gatechain = l1_kernel_rs::gatechain::GateChain::new();
    let spec = direct_spec();
    let gate = process_gate();

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
        .expect_err("unregistered capability must block");
    assert!(matches!(
        error,
        ProcessTableGroupRuntimeError::GateBlocked(_)
    ));

    gatechain.register_tools([PROCESS_SPAWN_CAPABILITY]);
    let mut denied_policy = direct_policy("/definitely/not-the-child");
    denied_policy.allowed_executables =
        Some(BTreeSet::from(["/definitely/not-the-child".to_owned()]));
    let error = runtime
        .spawn_gated_constrained(
            group,
            GatedProcessAdmission {
                gatechain: &gatechain,
                gate: &gate,
                spec: &spec,
                policy: denied_policy,
                terminal: None,
                options: None,
            },
        )
        .expect_err("constraint mismatch must block");
    assert!(matches!(
        error,
        ProcessTableGroupRuntimeError::Constraints(_)
    ));
    assert_eq!(runtime.bridge().active_count(), 0);

    let rows = audit.query(16, Some("agent-1"));
    assert!(rows.iter().any(|row| {
        row.op == "process.group.spawn.gate" && !row.success && row.error.contains("decision")
    }));
    assert!(
        rows.iter()
            .any(|row| { row.op == "process.group.spawn.constrained" && !row.success })
    );
    assert!(rows.iter().all(|row| !row.detail.contains("printf gated")));
}
