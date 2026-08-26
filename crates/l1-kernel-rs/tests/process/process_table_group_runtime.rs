//! Independent tests for ProcessTable-authoritative process groups.

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use l1_kernel_rs::process::{ProcessState, ProcessTable, ProcessTableConfig};
use l1_kernel_rs::process_adapter::ProcessAdapterConfig;
use l1_kernel_rs::process_group::{
    PROCESS_GROUP_SIGNAL_CONTRACT_VERSION, ProcessGroupSignalPort, ProcessGroupSignalReport,
    ProcessGroupState, ReaperBudget,
};
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
    let runtime = runtime(Arc::clone(&table), 1);
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
