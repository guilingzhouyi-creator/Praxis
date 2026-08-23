//! Independent tests for managed process-group coordination.

use std::thread;
use std::time::Duration;

use l1_kernel_rs::managed_process::ManagedProcessError;
use l1_kernel_rs::process_adapter::ProcessAdapterConfig;
use l1_kernel_rs::process_group::{ProcessGroupError, ProcessGroupState, ReaperBudget};
use l1_kernel_rs::process_group_runtime::{
    PROCESS_GROUP_RUNTIME_CONTRACT_VERSION, ProcessGroupRuntime, ProcessGroupRuntimeError,
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
