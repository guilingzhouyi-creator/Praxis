//! Independent tests for ProcessTable-owned managed-child execution.

use std::sync::{Arc, Barrier};
use std::thread;
use std::time::Duration;

use l1_kernel_rs::managed_process::{ManagedProcessState, ManagedWaitResult};
use l1_kernel_rs::process::{ProcessState, ProcessTable, ProcessTableConfig};
use l1_kernel_rs::process_adapter::ProcessAdapterConfig;
use l1_kernel_rs::process_bridge::{ProcessBridgeError, ProcessTableBridge};

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

fn setup(capacity: u32) -> (ProcessTableBridge, Arc<ProcessTable>) {
    let table = Arc::new(ProcessTable::new(ProcessTableConfig::new(
        64, "kernel", "init", 3, 1,
    )));
    let bridge = ProcessTableBridge::new(
        ProcessAdapterConfig::new(256).expect("config"),
        capacity,
        Arc::clone(&table),
    )
    .expect("bridge");
    (bridge, table)
}

#[test]
fn process_table_handle_is_the_only_public_identity() {
    let (bridge, table) = setup(2);
    let handle = bridge
        .spawn_args(&shell_args("printf bridge"), None)
        .expect("spawn");
    let running = bridge.snapshot(handle).expect("running snapshot");
    assert_eq!(running.handle, handle.raw());
    assert!(running.pid > 0);
    assert_eq!(running.table_state, ProcessState::Running);
    assert_eq!(running.managed_state, ManagedProcessState::Running);
    assert_eq!(
        table.get_by_handle(handle).expect("table row").pid,
        running.pid
    );

    let ManagedWaitResult::Finished(result) =
        bridge.wait(handle, Duration::from_secs(1)).expect("wait")
    else {
        panic!("child did not finish")
    };
    assert!(result.ok(), "{result:?}");
    let exited = bridge.snapshot(handle).expect("exited snapshot");
    assert_eq!(exited.table_state, ProcessState::Zombie);
    assert_eq!(exited.managed_state, ManagedProcessState::Exited);
    bridge.reap(handle).expect("reap");
    assert_eq!(bridge.active_count(), 0);
    assert!(table.get_by_handle(handle).is_none());
}

#[test]
fn termination_records_zombie_before_reap() {
    let (bridge, table) = setup(1);
    let handle = bridge
        .spawn_args(&shell_args("sleep 0.2"), None)
        .expect("spawn");
    let result = bridge
        .terminate(handle, Duration::from_secs(1))
        .expect("terminate");
    assert!(!result.ok());
    let snapshot = bridge.snapshot(handle).expect("snapshot");
    assert_eq!(snapshot.table_state, ProcessState::Zombie);
    assert_eq!(snapshot.managed_state, ManagedProcessState::Killed);
    bridge.reap(handle).expect("reap");
    assert!(table.get_by_handle(handle).is_none());
}

#[test]
fn spawn_failure_rolls_back_process_table_registration() {
    let (bridge, table) = setup(1);
    let error = bridge
        .spawn_args(&["praxis-bridge-missing-binary".to_owned()], None)
        .expect_err("missing child must fail");
    assert!(matches!(error, ProcessBridgeError::Managed(_)));
    assert_eq!(bridge.active_count(), 0);
    assert_eq!(table.list_processes(None).len(), 1);
}

#[test]
fn stale_bridge_handle_is_rejected_after_joint_reap() {
    let (bridge, table) = setup(1);
    let handle = bridge
        .spawn_args(&shell_args("printf stale"), None)
        .expect("spawn");
    bridge.wait(handle, Duration::from_secs(1)).expect("wait");
    bridge.reap(handle).expect("reap");
    assert_eq!(
        bridge.snapshot(handle),
        Err(ProcessBridgeError::TableUnavailable)
    );
    assert!(table.get_by_handle(handle).is_none());
}

#[test]
fn external_table_reap_fails_closed_without_leaking_managed_binding() {
    let (bridge, table) = setup(1);
    let handle = bridge
        .spawn_args(&shell_args("printf external-reap"), None)
        .expect("spawn");
    bridge.wait(handle, Duration::from_secs(1)).expect("wait");
    assert!(table.reap_handle(handle).is_some());

    assert_eq!(bridge.reap(handle), Err(ProcessBridgeError::TableReap));
    assert_eq!(bridge.active_count(), 0);
    assert_eq!(
        bridge.reap(handle),
        Err(ProcessBridgeError::TableUnavailable)
    );
}

#[test]
fn independent_bridges_share_table_without_name_collisions() {
    let table = Arc::new(ProcessTable::new(ProcessTableConfig::new(
        64, "kernel", "init", 3, 1,
    )));
    let first = ProcessTableBridge::new(
        ProcessAdapterConfig::new(256).expect("config"),
        1,
        Arc::clone(&table),
    )
    .expect("first bridge");
    let second = ProcessTableBridge::new(
        ProcessAdapterConfig::new(256).expect("config"),
        1,
        Arc::clone(&table),
    )
    .expect("second bridge");
    let first_handle = first
        .spawn_args(&shell_args("printf first"), None)
        .expect("first spawn");
    let second_handle = second
        .spawn_args(&shell_args("printf second"), None)
        .expect("second spawn");
    assert_ne!(first_handle, second_handle);
    first
        .wait(first_handle, Duration::from_secs(1))
        .expect("wait");
    second
        .wait(second_handle, Duration::from_secs(1))
        .expect("wait");
    first.reap(first_handle).expect("reap");
    second.reap(second_handle).expect("reap");
    assert_eq!(table.list_processes(None).len(), 1);
}

#[test]
fn finished_reaper_sweep_does_not_block_on_live_children() {
    let (bridge, table) = setup(2);
    let finished = bridge
        .spawn_args(&shell_args("printf finished"), None)
        .expect("finished spawn");
    let live = bridge
        .spawn_args(&shell_args("sleep 0.3"), None)
        .expect("live spawn");
    bridge
        .wait(finished, Duration::from_secs(1))
        .expect("finished wait");

    let report = bridge.reap_finished(2).expect("bounded reap");
    assert_eq!(
        report,
        l1_kernel_rs::process_bridge::ProcessReapReport {
            inspected: 2,
            reaped: 1,
            pending: 1,
            unavailable: 0,
            errors: 0,
        }
    );
    assert_eq!(bridge.active_count(), 1);
    assert!(table.get_by_handle(finished).is_none());
    bridge
        .terminate(live, Duration::from_secs(1))
        .expect("terminate");
    let terminal = bridge.reap_finished(1).expect("terminal reap");
    assert_eq!(terminal.reaped, 1);
    assert_eq!(terminal.errors, 0);
    assert_eq!(bridge.active_count(), 0);
}

#[test]
fn reaper_cleans_managed_child_after_external_table_transition() {
    let (bridge, table) = setup(1);
    let handle = bridge
        .spawn_args(&shell_args("printf conflict"), None)
        .expect("spawn");
    assert!(table.exit_handle(handle, 77, "external owner"));
    assert_eq!(
        bridge.wait(handle, Duration::from_secs(1)),
        Err(ProcessBridgeError::TableTransition)
    );

    let report = bridge.reap_finished(1).expect("reap conflict");
    assert_eq!(report.inspected, 1);
    assert_eq!(report.reaped, 0);
    assert_eq!(report.errors, 1);
    assert_eq!(bridge.active_count(), 0);
    assert!(table.get_by_handle(handle).is_none());
}

#[test]
fn finished_reaper_rejects_zero_budget_without_touching_children() {
    let (bridge, table) = setup(1);
    let handle = bridge
        .spawn_args(&shell_args("sleep 0.05"), None)
        .expect("spawn");
    assert_eq!(
        bridge.reap_finished(0),
        Err(ProcessBridgeError::InvalidReapBudget)
    );
    assert_eq!(bridge.active_count(), 1);
    assert!(table.get_by_handle(handle).is_some());
    bridge
        .terminate(handle, Duration::from_secs(1))
        .expect("terminate");
    bridge.reap_finished(1).expect("reap terminal");
}

#[test]
fn stop_sweep_is_bounded_and_reaps_selected_bindings() {
    let (bridge, table) = setup(2);
    bridge
        .spawn_args(&shell_args("sleep 5"), None)
        .expect("first spawn");
    bridge
        .spawn_args(&shell_args("sleep 5"), None)
        .expect("second spawn");

    let first = bridge
        .stop_all_once(1, Duration::from_secs(1))
        .expect("first stop sweep");
    assert_eq!(first.inspected, 1);
    assert_eq!(first.terminated, 1);
    assert_eq!(first.reaped, 1);
    assert_eq!(first.remaining, 1);
    assert_eq!(bridge.active_count(), 1);

    let second = bridge
        .stop_all_once(2, Duration::from_secs(1))
        .expect("second stop sweep");
    assert_eq!(second.reaped, 1);
    assert_eq!(second.remaining, 0);
    assert_eq!(bridge.active_count(), 0);
    assert_eq!(table.list_processes(None).len(), 1);
}

#[test]
fn stop_sweep_rejects_zero_budget_without_touching_bindings() {
    let (bridge, table) = setup(1);
    let handle = bridge
        .spawn_args(&shell_args("sleep 0.05"), None)
        .expect("spawn");
    assert_eq!(
        bridge.stop_all_once(0, Duration::ZERO),
        Err(ProcessBridgeError::InvalidReapBudget)
    );
    assert_eq!(bridge.active_count(), 1);
    assert!(table.get_by_handle(handle).is_some());
    bridge
        .stop_all_once(1, Duration::from_secs(1))
        .expect("cleanup");
}

#[test]
fn concurrent_children_keep_table_and_managed_books_in_sync() {
    let (bridge, table) = setup(4);
    let bridge = Arc::new(bridge);
    let barrier = Arc::new(Barrier::new(4));
    let workers = (0..4)
        .map(|worker| {
            let bridge = Arc::clone(&bridge);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                let handle = bridge
                    .spawn_args(&shell_args(&format!("printf worker-{worker}")), None)
                    .expect("spawn");
                let ManagedWaitResult::Finished(result) =
                    bridge.wait(handle, Duration::from_secs(1)).expect("wait")
                else {
                    panic!("child did not finish")
                };
                assert!(result.ok(), "{result:?}");
                bridge.reap(handle).expect("reap");
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().expect("worker join");
    }
    assert_eq!(bridge.active_count(), 0);
    assert_eq!(table.list_processes(None).len(), 1);
}
