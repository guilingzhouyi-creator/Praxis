//! Independent health aggregation tests for the Rust kernel.

use std::collections::BTreeMap;

use l1_kernel_rs::health::{HealthCheck, aggregate_health};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct HealthVectors {
    cases: Vec<HealthCase>,
}

#[derive(Debug, Deserialize)]
struct HealthCase {
    subsystems: BTreeMap<String, HealthCheck>,
    elapsed_ms: f64,
    expected: Value,
}

#[test]
fn shared_health_vectors_match_candidate() {
    let raw = include_str!("../../../../tests/fixtures/kernel_health_vectors.json");
    let vectors: HealthVectors = serde_json::from_str(raw).expect("valid health vectors");
    for case in vectors.cases {
        let actual = serde_json::to_value(aggregate_health(&case.subsystems, case.elapsed_ms))
            .expect("serializable health result");
        assert_eq!(actual, case.expected);
    }
}

#[test]
fn empty_health_is_healthy() {
    let result = aggregate_health(&BTreeMap::new(), 0.0);
    assert_eq!(result.status, "OK");
    assert_eq!(result.module_count, 0);
}
