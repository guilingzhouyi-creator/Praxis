//! Independent reputation-ledger policy tests for the Rust kernel.

use l1_kernel_rs::reputation::{DEFAULT_REPUTATION, ReputationLedger, ReputationPolicy};

#[test]
fn defaults_clamp_and_snapshot_are_deterministic() {
    let ledger = ReputationLedger::default();
    assert_eq!(ledger.get("unknown"), DEFAULT_REPUTATION);
    assert_eq!(ledger.set("agent-b", 2.0), Ok(1.0));
    assert_eq!(ledger.set("agent-a", -1.0), Ok(0.0));
    assert_eq!(
        ledger.snapshot().keys().collect::<Vec<_>>(),
        [&"agent-a", &"agent-b"]
    );
}

#[test]
fn outcome_deltas_are_applied_and_clamped() {
    let ledger = ReputationLedger::default();
    ledger.set("agent", 0.5).expect("set score");
    let after_task = ledger.record_task("agent", true).expect("task");
    let after_review = ledger.record_review("agent", false).expect("review");
    let after_dispute = ledger.record_dispute("agent", true).expect("dispute");
    assert!((after_task - 0.52).abs() < f64::EPSILON);
    assert!((after_review - 0.49).abs() < f64::EPSILON);
    assert!((after_dispute - 0.52).abs() < f64::EPSILON);
}

#[test]
fn non_finite_policy_and_scores_fail_closed() {
    let policy = ReputationPolicy {
        default_score: f64::NAN,
        ..ReputationPolicy::default()
    };
    assert!(ReputationLedger::new(policy).is_err());
    let ledger = ReputationLedger::default();
    assert!(ledger.set("agent", f64::NAN).is_err());
    assert!(ledger.adjust("agent", f64::INFINITY).is_err());
}

#[test]
fn custom_policy_is_explicit() {
    let policy = ReputationPolicy {
        default_score: 0.4,
        task_success_delta: 0.1,
        ..ReputationPolicy::default()
    };
    let ledger = ReputationLedger::new(policy).expect("valid policy");
    assert_eq!(ledger.policy(), policy);
    assert_eq!(ledger.record_task("agent", true), Ok(0.5));
}
