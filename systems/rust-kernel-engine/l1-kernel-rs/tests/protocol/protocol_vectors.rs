//! Cross-language tests for the Rust-owned v1 protocol boundary.

use l1_kernel_rs::protocol::{
    Message, MessageKind, ProtocolError, decode_message, decode_record, encode_message,
    encode_record,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;

#[test]
fn shared_ts_neutral_records_round_trip_canonically() {
    let fixtures: Vec<Value> = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/protocol_v1_records.json"
    ))
    .expect("valid protocol record fixtures");
    for fixture in fixtures {
        let line = serde_json::to_string(&fixture).expect("fixture serializes");
        let record = decode_record(&line).expect("record decodes");
        let encoded = encode_record(&record).expect("record encodes");
        assert_eq!(
            serde_json::from_str::<Value>(&encoded).expect("encoded json"),
            fixture
        );
    }
}

#[test]
fn unknown_record_fields_are_forward_compatible_but_versions_fail_closed() {
    let raw = json!({
        "record_type": "session_identity",
        "schema_version": 1,
        "data": {"session_id": "s", "terminal_id": "t", "process_id": "p", "future": true}
    });
    let record = decode_record(&raw.to_string()).expect("record decodes");
    assert!(!record.data.contains_key("future"));

    let future = json!({"record_type": "session_identity", "schema_version": 2, "data": {}});
    assert!(matches!(
        decode_record(&future.to_string()),
        Err(ProtocolError::InvalidContract(_))
    ));
}

#[test]
fn envelope_and_replay_cursor_are_transport_neutral() {
    let payload = BTreeMap::from([(String::from("name"), json!("status"))]);
    let message = Message::new("s-1", 7, MessageKind::Command, payload, "trace-1", 100.0);
    let line = encode_message(&message).expect("message encodes");
    assert_eq!(decode_message(&line).expect("message decodes"), message);

    let invalid =
        json!({"v": 1, "session_id": "s-1", "seq": 1, "ts": 0.0, "kind": "intent", "payload": {}});
    assert!(matches!(
        decode_message(&invalid.to_string()),
        Err(ProtocolError::InvalidContract(_))
    ));
}
