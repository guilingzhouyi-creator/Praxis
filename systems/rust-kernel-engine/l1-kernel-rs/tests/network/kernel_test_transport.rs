//! Independent TCP/UDP transport adapter tests for the Rust L1 kernel.

use std::collections::BTreeMap;
use std::io::Write;
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use l1_kernel_rs::contract::JsonValue;
use l1_kernel_rs::ports::{Endpoint, Message};
use l1_kernel_rs::transport::{
    TRANSPORT_CONTRACT_VERSION, TRANSPORT_DEFAULT_CHANNEL_CAPACITY, TRANSPORT_DEFAULT_PORT,
    TransportAdapter, TransportConfig, TransportError,
};
use serde_json::json;

fn wait_until<F>(mut predicate: F) -> bool
where
    F: FnMut() -> bool,
{
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        if predicate() {
            return true;
        }
        thread::sleep(Duration::from_millis(10));
    }
    predicate()
}

fn loopback_config() -> TransportConfig {
    TransportConfig::loopback_ephemeral()
}

fn message(message_type: &str) -> Message {
    Message {
        message_type: message_type.to_owned(),
        source: "sender".to_owned(),
        target: "receiver".to_owned(),
        payload: serde_json::from_value(json!({"value": 7})).expect("payload is JSON"),
        timestamp: 123.5,
        locale: "en".to_owned(),
        headers: BTreeMap::new(),
    }
}

fn endpoint(port: u16) -> Endpoint {
    Endpoint::new(format!("127.0.0.1:{port}"), "tcp")
}

fn send_frame(port: u16, frame: &[u8]) {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).expect("transport listener accepts");
    stream.write_all(frame).expect("frame writes");
}

#[test]
fn defaults_are_explicit_and_valid() {
    let config = TransportConfig::default();
    assert_eq!(config.port, TRANSPORT_DEFAULT_PORT);
    assert_eq!(config.channel_capacity, TRANSPORT_DEFAULT_CHANNEL_CAPACITY);
    config.validate().expect("default config is valid");
}

#[test]
fn configuration_and_tls_fail_closed_before_socket_bind() {
    let invalid = [
        TransportConfig {
            host: " \0 ".to_owned(),
            ..loopback_config()
        },
        TransportConfig {
            broadcast_address: " ".to_owned(),
            enable_discovery: true,
            ..loopback_config()
        },
        TransportConfig {
            broadcast_interval: Duration::ZERO,
            ..loopback_config()
        },
        TransportConfig {
            socket_timeout: Duration::ZERO,
            ..loopback_config()
        },
        TransportConfig {
            max_frame_bytes: 0,
            ..loopback_config()
        },
        TransportConfig {
            channel_capacity: 0,
            ..loopback_config()
        },
    ];
    for config in invalid {
        assert!(matches!(
            config.validate(),
            Err(TransportError::InvalidConfig(_))
        ));
    }

    let adapter = TransportAdapter::new();
    let tls = TransportConfig {
        tls_enabled: true,
        ..loopback_config()
    };
    assert_eq!(
        adapter.start("tls-node", tls),
        Err(TransportError::TlsUnsupported)
    );
    assert!(!adapter.is_running());
    assert!(!adapter.status().running);
}

#[test]
fn start_stop_reports_ephemeral_port_and_is_idempotent_after_stop() {
    let adapter = TransportAdapter::new();
    let report = adapter
        .start("transport-node", loopback_config())
        .expect("transport starts");
    assert_eq!(report.contract_version, TRANSPORT_CONTRACT_VERSION);
    assert_eq!(report.node_id, "transport-node");
    assert!(report.port > 0);
    assert_eq!(report.discovery_port, 0);
    assert!(adapter.is_running());
    assert_eq!(adapter.status().port, report.port);

    let stopped = adapter.stop();
    assert!(stopped.success);
    assert_eq!(stopped.contract_version, TRANSPORT_CONTRACT_VERSION);
    assert!(!adapter.is_running());
    assert_eq!(adapter.status().port, 0);
    assert_eq!(adapter.status().queued_messages, 0);

    let second_stop = adapter.stop();
    assert!(second_stop.success);
    assert_eq!(second_stop.remaining_messages, 0);
}

#[test]
fn start_failure_does_not_publish_partial_state_and_can_retry() {
    let occupied = TcpListener::bind(("127.0.0.1", 0)).expect("reserve test port");
    let occupied_port = occupied.local_addr().expect("port").port();
    let adapter = TransportAdapter::new();
    let config = TransportConfig {
        port: occupied_port,
        ..loopback_config()
    };
    assert!(matches!(
        adapter.start("failed-node", config),
        Err(TransportError::Io { operation, .. }) if operation == "tcp bind"
    ));
    assert!(!adapter.is_running());
    let status = adapter.status();
    assert_eq!(status.port, 0);
    assert_eq!(status.discovery_port, 0);
    assert_eq!(status.node_id, "");

    drop(occupied);
    let report = adapter
        .start("retry-node", loopback_config())
        .expect("retry starts after failed bind");
    assert!(report.port > 0);
    adapter.stop();
}

#[test]
fn tcp_frames_are_decoded_queued_and_dispatched_without_losing_remote_address() {
    let adapter = TransportAdapter::new();
    let handled = Arc::new(Mutex::new(Vec::new()));
    let handled_clone = Arc::clone(&handled);
    adapter
        .register_handler("message", move |received| {
            handled_clone.lock().expect("handler lock").push(received);
        })
        .expect("handler registers");
    let report = adapter
        .start("receiver", loopback_config())
        .expect("receiver starts");

    send_frame(
        report.port,
        br#"{"type":"message","from":"peer","to":"receiver","payload":{"value":7},"timestamp":123.5,"locale":"en"}"#,
    );
    assert!(wait_until(|| adapter.status().received_messages == 1));
    let received = adapter
        .receive(Some(Duration::from_secs(1)))
        .expect("receive succeeds")
        .expect("message is queued");
    assert_eq!(received.message_type, "message");
    assert_eq!(received.source, "peer");
    assert_eq!(
        received.headers.get("remote_addr"),
        Some(&JsonValue::String("127.0.0.1".to_owned()))
    );
    assert_eq!(handled.lock().expect("handler lock").len(), 1);
    adapter.stop();
}

#[test]
fn typed_send_round_trips_through_two_independent_adapters() {
    let receiver = TransportAdapter::new();
    let receiver_report = receiver
        .start("receiver", loopback_config())
        .expect("receiver starts");
    let sender = TransportAdapter::new();
    sender
        .start("sender", loopback_config())
        .expect("sender starts");

    let result = sender.send_message(&endpoint(receiver_report.port), &message("message"));
    assert!(result.success, "send failed: {}", result.error);
    assert!(wait_until(|| receiver.status().received_messages == 1));
    let received = receiver
        .receive(Some(Duration::from_secs(1)))
        .expect("receive succeeds")
        .expect("message arrives");
    assert_eq!(received.source, "sender");
    assert_eq!(received.target, "receiver");
    assert_eq!(received.timestamp, 123.5);
    assert_eq!(receiver.status().sent_messages, 0);
    assert_eq!(sender.status().sent_messages, 1);

    sender.stop();
    receiver.stop();
}

#[test]
fn bounded_queue_counts_drops_without_blocking_listener() {
    let receiver = TransportAdapter::new();
    let receiver_config = TransportConfig {
        channel_capacity: 1,
        ..loopback_config()
    };
    let receiver_report = receiver
        .start("receiver", receiver_config)
        .expect("receiver starts");
    let sender = TransportAdapter::new();
    sender
        .start("sender", loopback_config())
        .expect("sender starts");

    for value in 0..3 {
        let mut outgoing = message("message");
        outgoing.payload = serde_json::from_value(json!({"value": value})).expect("payload");
        let result = sender.send_message(&endpoint(receiver_report.port), &outgoing);
        assert!(result.success, "send failed: {}", result.error);
    }
    assert!(wait_until(|| receiver.status().received_messages == 3));
    let status = receiver.status();
    assert_eq!(status.queued_messages, 1);
    assert_eq!(status.dropped_messages, 2);

    sender.stop();
    receiver.stop();
}

#[test]
fn malformed_and_oversized_frames_are_rejected_and_counted() {
    let adapter = TransportAdapter::new();
    let config = TransportConfig {
        max_frame_bytes: 8,
        ..loopback_config()
    };
    let report = adapter.start("receiver", config).expect("receiver starts");

    send_frame(report.port, b"not-json\n");
    assert!(wait_until(|| adapter.status().decode_errors >= 1));
    send_frame(report.port, b"0123456789\n");
    assert!(wait_until(|| adapter.status().decode_errors >= 2));
    assert_eq!(adapter.status().received_messages, 0);
    assert!(adapter.receive(Some(Duration::ZERO)).is_ok());
    adapter.stop();
}

#[test]
fn handler_panics_are_contained_and_message_remains_available() {
    let adapter = TransportAdapter::new();
    adapter
        .register_handler("panic", |_| panic!("test handler panic"))
        .expect("handler registers");
    let report = adapter
        .start("receiver", loopback_config())
        .expect("starts");

    send_frame(
        report.port,
        br#"{"type":"panic","payload":{"ok":true},"timestamp":1.0}"#,
    );
    assert!(wait_until(|| adapter.status().handler_errors == 1));
    assert_eq!(adapter.status().received_messages, 1);
    assert!(
        adapter
            .receive(Some(Duration::from_secs(1)))
            .expect("receive succeeds")
            .is_some()
    );
    adapter.stop();
}

#[test]
fn handlers_can_be_replaced_and_removed_without_affecting_lifecycle() {
    let adapter = TransportAdapter::new();
    adapter
        .register_handler("message", |_| {})
        .expect("handler registers");
    assert!(adapter.unregister_handler("message"));
    assert!(!adapter.unregister_handler("message"));
    assert!(adapter.register_handler(" \0 ", |_| {}).is_err());
    adapter
        .start("receiver", loopback_config())
        .expect("starts");
    assert!(adapter.register_handler("message", |_| {}).is_ok());
    assert!(adapter.stop().success);
}

#[test]
fn transport_supports_explicit_udp_discovery_without_implicit_host_probe() {
    let adapter = TransportAdapter::new();
    let config = TransportConfig {
        enable_discovery: true,
        broadcast_address: "127.0.0.1".to_owned(),
        broadcast_interval: Duration::from_millis(20),
        ..loopback_config()
    };
    let report = adapter
        .start("discovery-node", config)
        .expect("discovery starts");
    assert!(report.discovery_enabled);
    assert!(report.discovery_port > 0);
    assert_eq!(adapter.status().discovery_port, report.discovery_port);
    thread::sleep(Duration::from_millis(40));
    adapter.stop();
}

#[test]
fn send_rejects_invalid_endpoints_and_message_values() {
    let adapter = TransportAdapter::new();
    let report = adapter.start("sender", loopback_config()).expect("starts");
    let invalid_hint = Endpoint::new(format!("127.0.0.1:{}", report.port), "udp");
    let result = adapter.send(&invalid_hint, br#"{}"#);
    assert!(!result.success);
    assert!(result.error.contains("unsupported transport hint"));

    let invalid_endpoint = Endpoint::new("not-an-endpoint", "tcp");
    let result = adapter.send(&invalid_endpoint, br#"{}"#);
    assert!(!result.success);

    let invalid_message = Message {
        message_type: " ".to_owned(),
        ..message("message")
    };
    let result = adapter.send_message(&invalid_endpoint, &invalid_message);
    assert!(!result.success);
    assert!(result.error.contains("invalid transport message"));
    adapter.stop();
}
