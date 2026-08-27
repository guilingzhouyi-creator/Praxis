//! Cross-language contract tests for the Rust RingChannel candidate.

use std::time::Duration;

use l1_kernel_rs::channel::RingChannel;
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct ChannelVectors {
    cases: Vec<ChannelCase>,
}

#[derive(Debug, Deserialize)]
struct ChannelCase {
    name: String,
    capacity: usize,
    overwrite: bool,
    operations: Vec<ChannelOperation>,
    expected_closed: bool,
}

#[derive(Debug, Deserialize)]
struct ChannelOperation {
    kind: String,
    value: Option<Value>,
    timeout_ms: Option<u64>,
    expected: Value,
}

#[test]
fn shared_channel_vectors_match_public_candidate_api() {
    let vectors: ChannelVectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_channel_vectors.json"
    ))
    .expect("valid channel vectors");
    for case in vectors.cases {
        let channel = RingChannel::new(case.capacity, case.overwrite).expect("valid channel");
        for operation in case.operations {
            let timeout = operation.timeout_ms.map(Duration::from_millis);
            let actual = match operation.kind.as_str() {
                "put" => channel
                    .put(operation.value.expect("put value"), timeout)
                    .into(),
                "get" => channel.get(timeout).unwrap_or(Value::Null),
                "peek" => channel.peek(timeout).unwrap_or(Value::Null),
                "size" => channel.size().into(),
                "drain" => channel.drain().into(),
                "utilization" => serde_json::to_value(channel.utilization()).expect("float value"),
                "close" => {
                    channel.close();
                    Value::Null
                }
                other => panic!("unknown channel operation: {other}"),
            };
            assert_eq!(actual, operation.expected, "{}", case.name);
        }
        assert_eq!(channel.is_closed(), case.expected_closed, "{}", case.name);
    }
}
