//! Independent watchdog mechanism tests for the Rust kernel.

use std::collections::BTreeMap;

use l1_kernel_rs::contract::ProcessState;
use l1_kernel_rs::watchdog::{
    REFERENCE_WATCHDOG_IDLE_LIMIT_MS, REFERENCE_WATCHDOG_INTERRUPT_LIMIT,
    REFERENCE_WATCHDOG_ZOMBIE_LIMIT, WatchdogPolicy, WatchdogPolicyError, WatchdogProcess,
    evaluate_watchdog,
};

#[test]
fn reference_policy_matches_python_thresholds() {
    let policy = WatchdogPolicy::reference();
    assert_eq!(policy.zombie_limit, REFERENCE_WATCHDOG_ZOMBIE_LIMIT);
    assert_eq!(policy.idle_limit_ms, REFERENCE_WATCHDOG_IDLE_LIMIT_MS);
    assert_eq!(policy.interrupt_limit, REFERENCE_WATCHDOG_INTERRUPT_LIMIT);
}

#[test]
fn zero_watchdog_thresholds_fail_closed() {
    assert_eq!(
        WatchdogPolicy::new(0, 1, 1),
        Err(WatchdogPolicyError::ZeroZombieLimit)
    );
    assert_eq!(
        WatchdogPolicy::new(1, 0, 1),
        Err(WatchdogPolicyError::ZeroIdleLimit)
    );
    assert_eq!(
        WatchdogPolicy::new(1, 1, 0),
        Err(WatchdogPolicyError::ZeroInterruptLimit)
    );
}

#[test]
fn evaluation_combines_zombie_and_idle_checks_in_process_order() {
    let policy = WatchdogPolicy::new(1, 300, 4).expect("policy");
    let processes = vec![
        WatchdogProcess::new(7, ProcessState::Ready, 301),
        WatchdogProcess::new(8, ProcessState::Zombie, 1_000),
        WatchdogProcess::new(9, ProcessState::Running, 300),
        WatchdogProcess::new(10, ProcessState::Blocked, 10_000),
        WatchdogProcess::new(11, ProcessState::Zombie, 4),
    ];
    let interrupts = BTreeMap::from([
        ("AGENT_CRASH".to_owned(), 5),
        ("CANCELLED".to_owned(), 4),
        ("DEADLOCK_DETECTED".to_owned(), 9),
    ]);

    let report = evaluate_watchdog(policy, &processes, &interrupts);
    assert_eq!(report.process_count, 5);
    assert_eq!(report.zombie_count, 2);
    assert!(report.zombie_limit_exceeded);
    assert_eq!(report.idle_processes.len(), 1);
    assert_eq!(report.idle_processes[0].pid, 7);
    assert_eq!(
        report
            .interrupt_alerts
            .iter()
            .map(|alert| alert.kind.as_str())
            .collect::<Vec<_>>(),
        vec!["AGENT_CRASH", "DEADLOCK_DETECTED"]
    );
    assert!(report.has_alerts());
    assert_eq!(report.alert_count(), 4);
}

#[test]
fn threshold_boundaries_are_not_alerts_and_reports_are_empty() {
    let policy = WatchdogPolicy::new(2, 300, 4).expect("policy");
    let processes = vec![
        WatchdogProcess::new(1, ProcessState::Zombie, 0),
        WatchdogProcess::new(2, ProcessState::Zombie, 0),
        WatchdogProcess::new(3, ProcessState::Ready, 300),
        WatchdogProcess::new(4, ProcessState::Running, 0),
        WatchdogProcess::new(5, ProcessState::Blocked, 301),
    ];
    let interrupts = BTreeMap::from([("CANCELLED".to_owned(), 4)]);

    let report = evaluate_watchdog(policy, &processes, &interrupts);
    assert!(!report.has_alerts());
    assert_eq!(report.alert_count(), 0);
    assert!(!report.zombie_limit_exceeded);
    assert!(report.idle_processes.is_empty());
    assert!(report.interrupt_alerts.is_empty());
}
