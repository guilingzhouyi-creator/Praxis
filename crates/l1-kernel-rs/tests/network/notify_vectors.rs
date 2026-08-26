//! Cross-language semantic vectors for the Rust notification buffer candidate.

use serde::Deserialize;
use serde_json::{Value, json};

use l1_kernel_rs::notify::NotificationBuffer;

#[derive(Debug, Deserialize)]
struct NotifyVectors {
    capacity: usize,
    events: Vec<NotifyEvent>,
    expected_recent: Vec<ExpectedNotification>,
    expected_dropped: u64,
}

#[derive(Debug, Deserialize)]
struct NotifyEvent {
    topic: String,
    payload: Value,
    timestamp: f64,
}

#[derive(Debug, Deserialize)]
struct ExpectedNotification {
    topic: String,
    payload: Value,
}

#[test]
fn shared_notify_vectors_match_rust_candidate() {
    let vectors: NotifyVectors = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_notify_vectors.json"
    ))
    .expect("valid notify vectors");
    let buffer = NotificationBuffer::new(vectors.capacity).expect("valid capacity");
    for event in vectors.events {
        buffer
            .publish(event.topic, event.payload, event.timestamp)
            .expect("event publishes");
    }
    let actual: Vec<Value> = buffer
        .recent(0)
        .into_iter()
        .map(|entry| json!({"topic": entry.topic, "payload": entry.payload}))
        .collect();
    let expected: Vec<Value> = vectors
        .expected_recent
        .into_iter()
        .map(|entry| json!({"topic": entry.topic, "payload": entry.payload}))
        .collect();
    assert_eq!(actual, expected);
    assert_eq!(buffer.stats().dropped, vectors.expected_dropped);
}
