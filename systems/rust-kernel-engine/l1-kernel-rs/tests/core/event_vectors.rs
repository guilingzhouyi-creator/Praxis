//! Cross-language contract tests for deterministic EventBus history behavior.

use std::time::Duration;

use l1_kernel_rs::contract::{EventBusStats, Signal};
use l1_kernel_rs::event::{EventBus, EventBusConfig};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct EventVectors {
    cases: Vec<EventCase>,
}

#[derive(Debug, Deserialize)]
struct EventCase {
    name: String,
    max_history: usize,
    workers: usize,
    max_queued: usize,
    registry_max: usize,
    signals: Vec<Signal>,
    expected_history: Vec<Signal>,
    expected_task_history: Vec<Signal>,
    expected_review_history: Vec<Signal>,
    expected_stats: EventBusStats,
}

#[test]
fn shared_event_history_vectors_match_public_candidate_api() {
    let vectors: EventVectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_event_vectors.json"
    ))
    .expect("valid event vectors");
    for case in vectors.cases {
        let bus = EventBus::new(EventBusConfig::new(
            case.max_history,
            case.workers,
            case.max_queued,
            case.registry_max,
        ));
        for signal in case.signals {
            assert_eq!(bus.emit(signal), 0, "{}", case.name);
        }
        assert_eq!(
            bus.history(None, 10),
            case.expected_history,
            "{}",
            case.name
        );
        assert_eq!(
            bus.history(Some("TASK_DONE"), 10),
            case.expected_task_history,
            "{}",
            case.name
        );
        assert_eq!(
            bus.history(Some("REVIEW_RESULT"), 10),
            case.expected_review_history,
            "{}",
            case.name
        );
        assert_eq!(bus.stats(), case.expected_stats, "{}", case.name);
        bus.shutdown(true, Some(Duration::from_secs(1)));
    }
}
