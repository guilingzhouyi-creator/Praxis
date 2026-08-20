//! Cross-language contract tests for the Rust L1 candidate boundary.
//!
//! These tests intentionally live outside `src/`: they consume public Rust
//! APIs and the shared Python/Rust fixture without reaching private internals.

use std::collections::BTreeMap;

use l1_kernel_rs::registry::{SummaryInput, aggregate_summary, snapshot_sections};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct RegistryVectors {
    cases: Vec<RegistryCase>,
}

#[derive(Debug, Deserialize)]
struct RegistryCase {
    sections: BTreeMap<String, Value>,
    modules: BTreeMap<String, Value>,
    process_count: usize,
    device_count: usize,
    syscalls: Vec<String>,
    timestamp: f64,
    #[serde(default)]
    healthy_status: Option<String>,
    expected_sections: BTreeMap<String, Value>,
    expected_summary: Value,
}

#[test]
fn shared_registry_vectors_match_public_candidate_api() {
    let raw = include_str!("../../../tests/fixtures/kernel_registry_vectors.json");
    let vectors: RegistryVectors = serde_json::from_str(raw).expect("valid registry vectors");
    for case in vectors.cases {
        assert_eq!(snapshot_sections(&case.sections), case.expected_sections);
        let actual = aggregate_summary(&SummaryInput {
            modules: case.modules,
            process_count: case.process_count,
            device_count: case.device_count,
            syscall_names: case.syscalls,
            timestamp: case.timestamp,
            healthy_status: case.healthy_status.unwrap_or_else(|| "PASS".to_owned()),
        });
        assert_eq!(actual, case.expected_summary);
    }
}
