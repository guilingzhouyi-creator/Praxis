//! Provider-neutral system-registry value aggregation candidate.
//!
//! Section values and runtime counts are supplied by an adapter. This module
//! performs no singleton discovery, clock reads, provider calls, or routing.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Build a deterministic snapshot of opaque JSON registry sections.
pub fn snapshot_sections(sections: &BTreeMap<String, Value>) -> BTreeMap<String, Value> {
    sections.clone()
}

/// Explicit values used to aggregate the system-registry overview.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SummaryInput {
    /// Module status records supplied by the health adapter.
    pub modules: BTreeMap<String, Value>,
    /// Number of processes observed by the process adapter.
    pub process_count: usize,
    /// Number of devices observed by the device adapter.
    pub device_count: usize,
    /// Syscall names supplied by the registry adapter, including duplicates.
    pub syscall_names: Vec<String>,
    /// Timestamp supplied by the caller; the candidate never reads a clock.
    pub timestamp: f64,
    /// Status value counted as healthy.
    #[serde(default = "default_healthy_status")]
    pub healthy_status: String,
}

/// Provide the default status string treated as healthy when none is configured.
fn default_healthy_status() -> String {
    "PASS".to_owned()
}

/// Aggregate explicit registry values with the Python wire shape.
pub fn aggregate_summary(input: &SummaryInput) -> Value {
    let healthy = input
        .modules
        .values()
        .filter(|value| {
            value.get("status").and_then(Value::as_str) == Some(input.healthy_status.as_str())
        })
        .count();
    serde_json::json!({
        "modules": {"total": input.modules.len(), "healthy": healthy},
        "processes": input.process_count,
        "devices": input.device_count,
        "syscalls": input.syscall_names.len(),
        "timestamp": input.timestamp,
    })
}
