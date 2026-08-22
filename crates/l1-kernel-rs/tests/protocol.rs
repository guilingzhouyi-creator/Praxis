//! Independent protocol mechanism tests for the Rust kernel.

use l1_kernel_rs::protocol::{
    Message, MessageKind, Outbox, ProtocolError, ProtocolRecord, decode_message, decode_record,
    encode_message, encode_record,
};
use serde_json::json;
use std::collections::BTreeMap;

fn payload(values: &[(&str, serde_json::Value)]) -> BTreeMap<String, serde_json::Value> {
    values
        .iter()
        .map(|(key, value)| ((*key).to_owned(), value.clone()))
        .collect()
}

#[test]
fn envelope_round_trip_is_canonical_and_versioned() {
    let message = Message::new(
        "s-1",
        7,
        MessageKind::Command,
        payload(&[("name", json!("status"))]),
        "trace-1",
        100.0,
    );
    let line = encode_message(&message).expect("message encodes");
    assert_eq!(
        line,
        r#"{"kind":"command","payload":{"name":"status"},"seq":7,"session_id":"s-1","trace_id":"trace-1","ts":100.0,"v":1}"#
    );
    assert_eq!(decode_message(&line).expect("message decodes"), message);
}

#[test]
fn invalid_envelopes_fail_closed() {
    assert!(matches!(
        decode_message("{}"),
        Err(ProtocolError::InvalidContract(_))
    ));
    let message = Message::new("s-1", 1, MessageKind::Intent, BTreeMap::new(), "", 0.0);
    assert!(encode_message(&message).is_err());
}

#[test]
fn record_unknown_fields_are_removed() {
    let raw = r#"{"record_type":"session_identity","schema_version":1,"data":{"session_id":"s","terminal_id":"t","process_id":"p","future":true}}"#;
    let record = decode_record(raw).expect("record decodes");
    assert!(!record.data.contains_key("future"));
    assert_eq!(
        encode_record(&record).expect("record encodes"),
        r#"{"data":{"cell_id":"","memory_scope":"","process_id":"p","role":"","session_id":"s","terminal_id":"t","user_id":""},"record_type":"session_identity","schema_version":1}"#
    );
}

#[test]
fn outbox_evicts_and_acknowledges_in_order() {
    let mut outbox = Outbox::new(2).expect("capacity");
    for seq in 1..=3 {
        outbox.append(Message::new(
            "s",
            seq,
            MessageKind::Result,
            payload(&[("success", json!(true))]),
            "",
            0.0,
        ));
    }
    assert_eq!(
        outbox
            .unacked()
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [2, 3]
    );
    outbox.ack(2);
    assert_eq!(
        outbox
            .unacked()
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [3]
    );
    assert_eq!(outbox.last_acked(), 2);
}

#[test]
fn record_type_is_public_value_only() {
    let record = ProtocolRecord {
        record_type: "evidence_ref".to_owned(),
        schema_version: 1,
        data: BTreeMap::from([
            ("evidence_id".to_owned(), json!("e-1")),
            ("session_id".to_owned(), json!("s-1")),
            ("input_seq".to_owned(), json!(1)),
            ("kind".to_owned(), json!("tool_result")),
            ("locator".to_owned(), json!("tool:x")),
            ("metadata".to_owned(), json!({})),
        ]),
    };
    assert!(encode_record(&record).is_ok());
}
