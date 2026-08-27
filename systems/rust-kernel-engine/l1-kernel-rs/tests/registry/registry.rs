//! Independent registry aggregation tests for the Rust kernel.

use std::collections::BTreeMap;

use l1_kernel_rs::registry::{SummaryInput, aggregate_summary, snapshot_sections};
use serde_json::Value;

#[test]
fn empty_inputs_are_deterministic() {
    let actual = aggregate_summary(&SummaryInput {
        modules: BTreeMap::new(),
        process_count: 0,
        device_count: 0,
        syscall_names: Vec::new(),
        timestamp: 0.0,
        healthy_status: "PASS".to_owned(),
    });
    assert_eq!(actual["modules"]["total"], 0);
    assert_eq!(
        snapshot_sections(&BTreeMap::new()),
        BTreeMap::<String, Value>::new()
    );
}
