//! Independent tests for the closure-backed host process-group adapter.

use std::sync::{Arc, Mutex};

use l1_kernel_rs::host_process_group_signal::HostProcessGroupSignalPort;
use l1_kernel_rs::process_group::{
    PROCESS_GROUP_CONTRACT_VERSION, PROCESS_GROUP_SIGNAL_CONTRACT_VERSION, ProcessGroupSignalPort,
    ProcessGroupSignalReport, ProcessGroupTerminationPlan,
};

fn plan(handles: Vec<u64>) -> ProcessGroupTerminationPlan {
    ProcessGroupTerminationPlan {
        contract_version: PROCESS_GROUP_CONTRACT_VERSION,
        group_id: 7,
        generation: 3,
        reason: "test stop".to_owned(),
        handles,
    }
}

#[test]
fn resolves_in_plan_order_and_reports_bounded_delivery() {
    let seen = Arc::new(Mutex::new(Vec::new()));
    let sent = Arc::clone(&seen);
    let adapter = HostProcessGroupSignalPort::new(
        |handle| Ok(handle + 1000),
        move |targets| {
            sent.lock().expect("sender lock").extend_from_slice(targets);
            Ok(2)
        },
    );
    let current = adapter.send_stop(&plan(vec![4, 9, 12])).expect("send");
    assert_eq!(
        current.contract_version,
        PROCESS_GROUP_SIGNAL_CONTRACT_VERSION
    );
    assert_eq!(current.group_id, 7);
    assert_eq!(current.generation, 3);
    assert_eq!(current.attempted, 3);
    assert_eq!(current.delivered, 2);
    assert_eq!(*seen.lock().expect("seen lock"), vec![1004, 1009, 1012]);
}

#[test]
fn resolver_failure_prevents_partial_sender_dispatch() {
    let called = Arc::new(Mutex::new(false));
    let sender_called = Arc::clone(&called);
    let adapter = HostProcessGroupSignalPort::new(
        |handle| {
            if handle == 9 {
                Err("stale mapping".to_owned())
            } else {
                Ok(handle)
            }
        },
        move |_| {
            *sender_called.lock().expect("sender lock") = true;
            Ok(1)
        },
    );
    let error = adapter
        .send_stop(&plan(vec![4, 9]))
        .expect_err("resolver error");
    assert!(error.contains("stale mapping"));
    assert!(!*called.lock().expect("called lock"));
}

#[test]
fn invalid_sender_count_and_invalid_plan_fail_closed() {
    let adapter = HostProcessGroupSignalPort::new(Ok, |_| Ok(4));
    let error = adapter
        .send_stop(&plan(vec![1, 2]))
        .expect_err("over-report");
    assert!(error.contains("more deliveries"));

    let mut duplicate = plan(vec![1, 1]);
    assert!(adapter.send_stop(&duplicate).is_err());
    duplicate.handles = vec![0];
    assert!(adapter.send_stop(&duplicate).is_err());
    duplicate.handles = vec![1];
    duplicate.generation = 0;
    assert!(adapter.send_stop(&duplicate).is_err());
}

#[test]
fn empty_plan_is_a_valid_noop_batch() {
    let adapter = HostProcessGroupSignalPort::new(
        |_| panic!("resolver must not run"),
        |targets| {
            assert!(targets.is_empty());
            Ok(0)
        },
    );
    let report = adapter.send_stop(&plan(Vec::new())).expect("empty plan");
    assert_eq!(
        report,
        ProcessGroupSignalReport {
            contract_version: PROCESS_GROUP_SIGNAL_CONTRACT_VERSION,
            group_id: 7,
            generation: 3,
            attempted: 0,
            delivered: 0,
        }
    );
}
