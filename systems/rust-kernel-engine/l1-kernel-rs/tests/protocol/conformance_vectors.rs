//! Cross-language conformance vectors for protocol v1 (Rust runner).
//!
//! Consumes the fixture frozen from the normative TS engine:
//! `../../../tests/fixtures/protocol_v1_conformance.json` relative to the
//! crate manifest. Canonical bytes must match byte-for-byte; invalid
//! frames must fail closed; R1 outbox semantics must hold.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde_json::{Value, json};

use l1_kernel_rs::protocol::{
    Message, MessageKind, decode_message, encode_message, validate_message,
};

#[derive(Deserialize)]
struct Fixture {
    canonical_envelopes: Vec<CanonicalCase>,
    invalid_frames: Vec<InvalidFrame>,
    outbox_recovery: Vec<OutboxCase>,
}

#[derive(Deserialize)]
struct CanonicalCase {
    name: String,
    fields: Value,
    expected_line: String,
}

#[derive(Deserialize)]
struct InvalidFrame {
    name: String,
    line: String,
    error_contains_any: Vec<String>,
}

#[derive(Deserialize)]
struct OutboxCase {
    name: String,
    maxlen: usize,
    append_seqs: Vec<u64>,
    ack: Option<u64>,
    expect_default_unacked: Vec<i64>,
    #[allow(dead_code)]
    expect_recovery_from_minus_one: Vec<i64>,
}

fn fixture() -> Fixture {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../tests/fixtures/protocol_v1_conformance.json");
    let raw = std::fs::read_to_string(path).expect("fixture readable");
    serde_json::from_str(&raw).expect("fixture parses")
}

fn build_message(fields: &Value) -> Message {
    let payload = fields["payload"]
        .as_object()
        .expect("payload object")
        .iter()
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect::<BTreeMap<_, _>>();
    Message::new(
        fields["session_id"].as_str().expect("session_id"),
        fields["seq"].as_u64().expect("seq"),
        match fields["kind"].as_str().expect("kind") {
            "ack" => MessageKind::Ack,
            "command" => MessageKind::Command,
            "control" => MessageKind::Control,
            "event" => MessageKind::Event,
            "intent" => MessageKind::Intent,
            "result" => MessageKind::Result,
            _ => MessageKind::StreamChunk,
        },
        payload,
        fields["trace_id"].as_str().unwrap_or_default(),
        fields["ts"].as_f64().expect("ts"),
    )
}

#[test]
fn canonical_encoding_matches_frozen_bytes() {
    for case in fixture().canonical_envelopes {
        let message = build_message(&case.fields);
        assert!(
            validate_message(&message).is_empty(),
            "{} must validate",
            case.name
        );
        let line = encode_message(&message).expect("encodes");
        assert_eq!(
            line, case.expected_line,
            "canonical bytes for {}",
            case.name
        );
        assert_eq!(
            decode_message(&line).expect("round trips"),
            message,
            "round trip for {}",
            case.name
        );
    }
}

#[test]
fn invalid_frames_fail_closed() {
    for case in fixture().invalid_frames {
        let error = decode_message(&case.line)
            .err()
            .unwrap_or_else(|| panic!("{} must be rejected", case.name));
        let text = error.to_string();
        assert!(
            case.error_contains_any
                .iter()
                .any(|fragment| text.contains(fragment)),
            "{name}: {text}",
            name = case.name,
            text = text
        );
    }
}

#[test]
fn outbox_recovery_semantics_r1() {
    for case in fixture().outbox_recovery {
        let mut box_ = l1_kernel_rs::protocol::Outbox::new(case.maxlen).expect("valid maxlen");
        for seq in &case.append_seqs {
            box_.append(Message::new(
                "s",
                *seq,
                MessageKind::Intent,
                BTreeMap::from([("text".to_owned(), json!("x"))]),
                "",
                1.0,
            ));
        }
        if let Some(ack) = case.ack {
            box_.ack(ack);
        }
        let default_window: Vec<i64> = box_
            .unacked()
            .iter()
            .map(|message| message.seq as i64)
            .collect();
        assert_eq!(default_window, case.expect_default_unacked, "{}", case.name);
        let recovery: Vec<i64> = box_
            .unacked_after(-1)
            .iter()
            .map(|message| message.seq as i64)
            .collect();
        assert_eq!(
            recovery, case.expect_recovery_from_minus_one,
            "{}",
            case.name
        );
    }
}
