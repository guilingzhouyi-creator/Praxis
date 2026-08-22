//! Independent tests for the Rust JSONL protocol gate.

use l1_kernel_rs::protocol_host::{
    DEFAULT_MAX_FRAME_BYTES, ProtocolHost, ProtocolHostConfig, ProtocolHostError,
};

const VALID_COMMAND: &str =
    r#"{"ts":100.0,"payload":{"name":"status"},"kind":"command","seq":7,"v":1,"session_id":"s-1"}"#;

#[test]
fn gate_canonicalizes_valid_envelopes_without_dispatching_them() {
    let gate = ProtocolHost::default();
    assert_eq!(
        gate.canonicalize_line(VALID_COMMAND)
            .expect("valid envelope"),
        r#"{"kind":"command","payload":{"name":"status"},"seq":7,"session_id":"s-1","ts":100.0,"v":1}"#
    );
    assert_eq!(gate.config().max_frame_bytes(), DEFAULT_MAX_FRAME_BYTES);
}

#[test]
fn gate_rejects_oversized_frames_before_protocol_decode() {
    let gate = ProtocolHost::new(ProtocolHostConfig::new(8).expect("positive bound"));
    assert_eq!(
        gate.canonicalize_line(VALID_COMMAND),
        Err(ProtocolHostError::FrameTooLarge {
            actual_bytes: VALID_COMMAND.len(),
            max_bytes: 8,
        })
    );
}

#[test]
fn gate_preserves_fail_closed_protocol_errors() {
    let gate = ProtocolHost::default();
    let error = gate
        .canonicalize_line("{\"v\":1}")
        .expect_err("invalid envelope");
    assert!(matches!(error, ProtocolHostError::Protocol(_)));
}

#[test]
fn gate_rejects_zero_frame_limit() {
    assert_eq!(
        ProtocolHostConfig::new(0),
        Err("protocol frame limit must be positive")
    );
}
