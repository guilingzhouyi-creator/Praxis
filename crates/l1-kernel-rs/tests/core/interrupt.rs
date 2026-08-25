//! Independent interrupt-table tests for the Rust kernel.

use l1_kernel_rs::interrupt::{InterruptTable, InterruptType};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct InterruptVector {
    events: Vec<EventVector>,
    expected_counts: serde_json::Value,
    recent_limit: usize,
    expected_recent: serde_json::Value,
}

#[derive(Debug, Deserialize)]
struct EventVector {
    #[serde(rename = "type")]
    interrupt_type: String,
    #[serde(default)]
    agent_id: String,
    #[serde(default)]
    reason: String,
    data: Option<serde_json::Value>,
}

#[test]
fn type_names_are_closed_and_wire_stable() {
    for name in [
        "AGENT_CRASH",
        "RESOURCE_EXHAUSTION",
        "DEADLOCK_DETECTED",
        "OOM_KILL",
        "CANCELLED",
    ] {
        let kind = InterruptType::parse(name).expect("known interrupt type");
        assert_eq!(kind.as_str(), name);
    }
    assert!(InterruptType::parse("UNKNOWN").is_none());
}

#[test]
fn bounded_history_and_per_type_sequence_match_python_shape() {
    let table = InterruptTable::with_limits(2, 20);
    table.raise(InterruptType::Cancelled, "agent-a", "first", None);
    table.raise(InterruptType::Cancelled, "agent-a", "second", None);
    let third = table.raise(
        InterruptType::ResourceExhaustion,
        "agent-b",
        "pressure",
        Some(serde_json::Value::Null),
    );
    assert_eq!(third.sequence, 1);
    assert_eq!(table.counts()["CANCELLED"], 2);
    assert_eq!(table.recent(Some(20)).len(), 2);
    assert_eq!(table.recent(Some(0)).len(), 2);
    assert_eq!(table.recent(None)[0].sequence, 2);
}

#[test]
fn shared_interrupt_vectors_match_python_reference() {
    let vectors: Vec<InterruptVector> = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_interrupt_vectors.json"
    ))
    .expect("interrupt fixture must be valid JSON");
    for vector in vectors {
        let table = InterruptTable::new();
        for event in vector.events {
            let interrupt_type = InterruptType::parse(&event.interrupt_type)
                .expect("fixture interrupt type must be known");
            table.raise(interrupt_type, event.agent_id, event.reason, event.data);
        }
        assert_eq!(
            serde_json::to_value(table.counts()).expect("counts serialize"),
            vector.expected_counts
        );
        assert_eq!(
            serde_json::to_value(table.recent(Some(vector.recent_limit)))
                .expect("history serializes"),
            vector.expected_recent
        );
    }
}
