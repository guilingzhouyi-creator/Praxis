//! Independent process-table tests for the Rust kernel candidate.

use l1_kernel_rs::process::ProcessState;
use l1_kernel_rs::process::{Pcb, ProcessTable, ProcessTableConfig};
use l1_kernel_rs::substrate::ProcessHandle;

fn table() -> ProcessTable {
    ProcessTable::new(ProcessTableConfig::new(32, "kernel", "init", 3, 1))
}

#[test]
fn pcb_snapshot_and_resource_methods_preserve_python_shape() {
    let mut pcb = Pcb::new(1, "agent-a", "worker", 0, 2);
    pcb.record_tokens(10, 4);
    pcb.record_card();
    pcb.record_scout(2);
    pcb.record_scout(-1);
    pcb.record_cpu(1.5);
    let snapshot = pcb.snapshot();
    assert_eq!(snapshot["state"], "READY");
    assert_eq!(snapshot["tokens_allocated"], 10);
    assert_eq!(snapshot["tokens_used"], 4);
    assert_eq!(snapshot["scouts_active"], 1);
    assert!(snapshot.contains_key("uptime"));
    assert!(snapshot.contains_key("idle"));
}

#[test]
fn table_installs_kernel_and_runs_fsm_cycle() {
    let table = table();
    let init = table.get(0).unwrap();
    assert_eq!(init.state, ProcessState::Running);
    let pcb = table.spawn("agent-a", "worker", 0, None);
    assert_eq!(pcb.state, ProcessState::Ready);
    assert!(table.set_running("agent-a"));
    assert!(table.yield_process("agent-a"));
    assert_eq!(
        table.get_by_name("agent-a").unwrap().state,
        ProcessState::Ready
    );
}

#[test]
fn cancel_is_idempotent_and_blocks_future_run() {
    let table = table();
    table.spawn("agent-a", "worker", 0, None);
    assert!(table.cancel("agent-a", "user abort"));
    let pcb = table.get_by_name("agent-a").unwrap();
    assert_eq!(pcb.state, ProcessState::Stopped);
    assert!(pcb.cancelled);
    assert!(table.is_cancelled("agent-a"));
    assert!(table.cancel("agent-a", "again"));
    assert!(!table.set_running("agent-a"));
}

#[test]
fn exit_reap_and_audit_are_bounded_and_ordered() {
    let table = table();
    let pcb = table.spawn("agent-a", "worker", 0, None);
    assert!(table.exit(pcb.pid, 3, "shutdown"));
    assert_eq!(table.get(pcb.pid).unwrap().state, ProcessState::Zombie);
    let log = table.audit_log(10);
    assert_eq!(log.len(), 2);
    assert_eq!(log[0]["op"], "spawn");
    assert_eq!(log[1]["op"], "exit");
    assert!(table.reap(pcb.pid).is_some());
    assert!(table.reap(pcb.pid).is_none());
    assert_eq!(table.audit_log(10).len(), 3);
}

#[test]
fn identity_and_resource_summary_are_explicit() {
    let table = table();
    let pcb = table.spawn("agent-a", "worker", 0, None);
    assert!(table.mark_identity_verified("agent-a"));
    assert!(table.record_tokens(pcb.pid, 7, 2));
    assert!(table.record_card(pcb.pid));
    assert!(table.record_scout(pcb.pid, 1));
    let snapshot = table.get(pcb.pid).unwrap();
    assert!(snapshot.identity_verified);
    assert_eq!(snapshot.resources.tokens_allocated, 7);
    assert_eq!(snapshot.resources.cards_processed, 1);
    assert_eq!(table.resource_summary()["tokens"], 7);
    assert_eq!(table.resource_summary()["cards"], 1);
}

#[test]
fn typed_process_handles_are_fail_closed_after_generation_or_reap() {
    let table = table();
    let pcb = table.spawn("agent-a", "worker", 0, None);
    let handle = table.handle_for_pid(pcb.pid).expect("live handle");
    assert_eq!(
        table.get_by_handle(handle).expect("handle lookup").pid,
        pcb.pid
    );
    let stale_generation = ProcessHandle::new(handle.slot(), 2).expect("stale handle");
    assert!(table.get_by_handle(stale_generation).is_none());
    assert!(table.exit_handle(handle, 0, "done"));
    assert!(table.reap_handle(handle).is_some());
    assert!(table.get_by_handle(handle).is_none());
    assert!(table.reap_handle(handle).is_none());
}
