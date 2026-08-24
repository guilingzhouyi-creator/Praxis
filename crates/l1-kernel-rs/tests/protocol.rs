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
fn canonical_json_golden_vectors_match_python_reference() {
    // Frozen against `python -c "from l2.protocol.envelope import ..."`
    // outputs with ts pinned to 100.0: recursive key sort + same field order.
    let cases: Vec<(Message, &str)> = vec![
        (
            Message::new(
                "s-1",
                7,
                MessageKind::Command,
                payload(&[("name", json!("status")), ("args", json!(["a", "b"]))]),
                "",
                100.0,
            ),
            r#"{"kind":"command","payload":{"args":["a","b"],"name":"status"},"seq":7,"session_id":"s-1","trace_id":"","ts":100.0,"v":1}"#,
        ),
        (
            Message::new(
                "s-2",
                0,
                MessageKind::Intent,
                payload(&[("text", json!("hello world"))]),
                "",
                100.0,
            ),
            r#"{"kind":"intent","payload":{"text":"hello world"},"seq":0,"session_id":"s-2","trace_id":"","ts":100.0,"v":1}"#,
        ),
        (
            Message::new(
                "s-3",
                42,
                MessageKind::Event,
                payload(&[
                    ("event_type", json!("tick")),
                    ("data", json!({"z": 1, "a": [3, {"y": 2, "x": 1}]})),
                ]),
                "",
                100.0,
            ),
            r#"{"kind":"event","payload":{"data":{"a":[3,{"x":1,"y":2}],"z":1},"event_type":"tick"},"seq":42,"session_id":"s-3","trace_id":"","ts":100.0,"v":1}"#,
        ),
        (
            Message::new(
                "s-4",
                9,
                MessageKind::Ack,
                payload(&[("ack_seq", json!(9)), ("view_id", json!("view-web"))]),
                "",
                100.0,
            ),
            r#"{"kind":"ack","payload":{"ack_seq":9,"view_id":"view-web"},"seq":9,"session_id":"s-4","trace_id":"","ts":100.0,"v":1}"#,
        ),
        (
            Message::new(
                "s-5",
                1,
                MessageKind::Control,
                payload(&[("op", json!("attach")), ("session_id", json!("s-5"))]),
                "",
                100.0,
            ),
            r#"{"kind":"control","payload":{"op":"attach","session_id":"s-5"},"seq":1,"session_id":"s-5","trace_id":"","ts":100.0,"v":1}"#,
        ),
        (
            Message::new(
                "s-6",
                5,
                MessageKind::Result,
                payload(&[("success", json!(true)), ("output", json!("ok"))]),
                "",
                100.0,
            ),
            r#"{"kind":"result","payload":{"output":"ok","success":true},"seq":5,"session_id":"s-6","trace_id":"","ts":100.0,"v":1}"#,
        ),
        (
            Message::new(
                "s-7",
                8,
                MessageKind::StreamChunk,
                payload(&[("data", json!("partial"))]),
                "",
                100.0,
            ),
            r#"{"kind":"stream_chunk","payload":{"data":"partial"},"seq":8,"session_id":"s-7","trace_id":"","ts":100.0,"v":1}"#,
        ),
    ];
    for (message, expected) in cases {
        let line = encode_message(&message).expect("message encodes");
        assert_eq!(
            &line, expected,
            "golden vector mismatch for {:?}",
            message.kind
        );
        assert_eq!(decode_message(&line).expect("decodes"), message);
    }
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
fn seq_bounds_fail_closed_and_clamp_safely() {
    // Negative seq is rejected at decode (python parity: non-negative int).
    assert!(matches!(
        decode_message(
            r#"{"kind":"command","payload":{"name":"x"},"seq":-1,"session_id":"s","trace_id":"","ts":1.0,"v":1}"#
        ),
        Err(ProtocolError::InvalidContract(_))
    ));
    // Float seq is rejected too.
    assert!(matches!(
        decode_message(
            r#"{"kind":"command","payload":{"name":"x"},"seq":1.5,"session_id":"s","trace_id":"","ts":1.0,"v":1}"#
        ),
        Err(ProtocolError::InvalidContract(_))
    ));
    // u64::MAX round-trips exactly (python int parity, no precision loss).
    let max = Message::new(
        "s",
        u64::MAX,
        MessageKind::Event,
        payload(&[("event_type", json!("edge"))]),
        "",
        100.0,
    );
    let line = encode_message(&max).expect("u64::MAX encodes");
    assert!(line.contains(r#""seq":18446744073709551615"#));
    assert_eq!(decode_message(&line).expect("decodes"), max);
}

#[test]
fn outbox_ack_clamps_huge_seqs_without_breaking_replay() {
    let mut outbox = Outbox::new(4).expect("capacity");
    for seq in [1u64, 2, 3, 4] {
        outbox.append(Message::new(
            "s",
            seq,
            MessageKind::Event,
            payload(&[("event_type", json!("tick"))]),
            "",
            0.0,
        ));
    }
    // A client seq above i64::MAX must not panic or corrupt the window.
    outbox.ack(u64::MAX);
    assert_eq!(outbox.last_acked(), i64::MAX);
    // Replay window still intact (non-destructive).
    assert_eq!(outbox.unacked().len(), 4);
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
        [2, 3]
    );
    assert_eq!(outbox.last_acked(), 2);
    assert_eq!(
        outbox
            .unacked_after(1)
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [2, 3]
    );
    assert_eq!(
        outbox
            .unacked_after(2)
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [3]
    );
}

#[test]
fn multi_view_replay_window_survives_other_view_acks() {
    // View A acknowledges early; view B (lagging) must still replay the full
    // retained window. A destructive ack would erase B's replay data.
    let mut outbox = Outbox::new(8).expect("capacity");
    for seq in 1..=5 {
        outbox.append(Message::new(
            "s",
            seq,
            MessageKind::Event,
            payload(&[("event_type", json!("tick"))]),
            "",
            0.0,
        ));
    }
    // View A races ahead.
    outbox.ack(4);
    // View B still attached at -1: full replay must be available.
    assert_eq!(
        outbox
            .unacked_after(-1)
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [1, 2, 3, 4, 5],
        "view B replay window must survive view A ack"
    );
    // View B advancing to 2 still sees 3..5.
    assert_eq!(
        outbox
            .unacked_after(2)
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [3, 4, 5]
    );
}

#[test]
fn outbox_eviction_bounds_replay_window_but_keeps_ack_cursor() {
    let mut outbox = Outbox::new(2).expect("capacity");
    outbox.ack(99);
    for seq in 100..=102 {
        outbox.append(Message::new(
            "s",
            seq,
            MessageKind::Event,
            payload(&[("event_type", json!("tick"))]),
            "",
            0.0,
        ));
    }
    // Capacity bound still applies to the buffered window.
    assert_eq!(outbox.unacked().len(), 2);
    // Ack cursor stays monotonic across eviction.
    assert_eq!(outbox.last_acked(), 99);
    assert_eq!(
        outbox
            .unacked_after(99)
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [101, 102]
    );
}

#[test]
fn regressive_acks_never_move_the_cursor_backward() {
    let mut outbox = Outbox::new(4).expect("capacity");
    outbox.ack(10);
    outbox.ack(3);
    assert_eq!(outbox.last_acked(), 10);
}

#[test]
fn shared_watermark_is_the_lagging_view_cursor() {
    // Mirrors SessionMultiplexer.watermark (session-manager.ts): the shared
    // watermark equals the lowest lastAcked across attached views.
    use l1_kernel_rs::protocol::SessionMultiplexer;
    let mut mux = SessionMultiplexer::new();
    assert_eq!(mux.watermark(), -1, "no views -> watermark -1");
    assert!(mux.view_ids().is_empty());

    mux.attach("view-a", "s-1");
    mux.attach("view-b", "s-1");
    for seq in 1..=5 {
        mux.emit(Message::new(
            "s-1",
            seq,
            MessageKind::Event,
            payload(&[("event_type", json!("tick"))]),
            "",
            0.0,
        ));
    }
    // View A races to 4; watermark must stay at view B's -1.
    mux.ack("view-a", 4);
    assert_eq!(mux.watermark(), -1);
    // View B advances to 2; watermark follows the laggard.
    mux.ack("view-b", 2);
    assert_eq!(mux.watermark(), 2);
    // View B catches up fully; watermark now equals view A's position.
    mux.ack("view-b", 5);
    assert_eq!(mux.watermark(), 4);
    // Detached views no longer pull the watermark (cursor retained).
    mux.detach("view-a");
    assert_eq!(mux.watermark(), 5);
    // Replay windows over the shared stream are never erased by acking.
    assert_eq!(
        mux.replay_after(-1)
            .iter()
            .map(|message| message.seq)
            .collect::<Vec<_>>(),
        [1, 2, 3, 4, 5]
    );
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
