//! Cross-language semantic vectors for the Rust reputation ledger candidate.

use std::collections::BTreeMap;

use l1_kernel_rs::reputation::{ReputationLedger, ReputationPolicy};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct ReputationVectors {
    policy: PolicyVector,
    cases: Vec<ReputationCase>,
}

#[derive(Debug, Deserialize)]
struct PolicyVector {
    default_score: f64,
    min_score: f64,
    max_score: f64,
    task_success_delta: f64,
    task_failure_delta: f64,
    review_approved_delta: f64,
    review_rejected_delta: f64,
    dispute_upheld_delta: f64,
    dispute_dismissed_delta: f64,
}

#[derive(Debug, Deserialize)]
struct ReputationCase {
    name: String,
    operations: Vec<ReputationOperation>,
    snapshot: BTreeMap<String, f64>,
}

#[derive(Debug, Deserialize)]
struct ReputationOperation {
    kind: String,
    agent_id: String,
    score: Option<f64>,
    success: Option<bool>,
    approved: Option<bool>,
    upheld: Option<bool>,
    expected: Option<f64>,
}

fn assert_score(actual: f64, expected: f64, case: &str) {
    assert!(
        (actual - expected).abs() < 1e-12,
        "{case}: {actual} != {expected}"
    );
}

#[test]
fn shared_reputation_vectors_match_rust_candidate() {
    let vectors: ReputationVectors = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_reputation_vectors.json"
    ))
    .expect("valid reputation vectors");
    let policy = ReputationPolicy {
        default_score: vectors.policy.default_score,
        min_score: vectors.policy.min_score,
        max_score: vectors.policy.max_score,
        task_success_delta: vectors.policy.task_success_delta,
        task_failure_delta: vectors.policy.task_failure_delta,
        review_approved_delta: vectors.policy.review_approved_delta,
        review_rejected_delta: vectors.policy.review_rejected_delta,
        dispute_upheld_delta: vectors.policy.dispute_upheld_delta,
        dispute_dismissed_delta: vectors.policy.dispute_dismissed_delta,
    };
    for case in vectors.cases {
        let ledger = ReputationLedger::new(policy).expect("valid policy");
        for operation in case.operations {
            let actual = match operation.kind.as_str() {
                "get" => ledger.get(&operation.agent_id),
                "set" => ledger
                    .set(
                        operation.agent_id.as_str(),
                        operation.score.expect("set score"),
                    )
                    .expect("set succeeds"),
                "record_task" => ledger
                    .record_task(
                        operation.agent_id.as_str(),
                        operation.success.expect("task outcome"),
                    )
                    .expect("task succeeds"),
                "record_review" => ledger
                    .record_review(
                        operation.agent_id.as_str(),
                        operation.approved.expect("review outcome"),
                    )
                    .expect("review succeeds"),
                "record_dispute" => ledger
                    .record_dispute(
                        operation.agent_id.as_str(),
                        operation.upheld.expect("dispute outcome"),
                    )
                    .expect("dispute succeeds"),
                other => panic!("unknown reputation operation: {other}"),
            };
            if let Some(expected) = operation.expected {
                assert_score(actual, expected, &case.name);
            }
        }
        for (agent_id, expected) in case.snapshot {
            assert_score(ledger.get(&agent_id), expected, &case.name);
        }
    }
}
