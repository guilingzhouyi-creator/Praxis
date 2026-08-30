//! Integration tests for explicit protocol-host/runtime composition.

use std::sync::Arc;
use std::time::Duration;

use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::contract::CapabilityResult;
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::protocol::{Message, MessageKind, encode_message};
use l1_kernel_rs::protocol_host::{ProtocolHostConfig, ProtocolHostError};
use l1_kernel_rs::protocol_host_runtime::{ProtocolHostRuntime, ProtocolHostRuntimeConfig};
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig};
use l1_kernel_rs::settings_protocol::{SettingsAuthorizer, StaticSettingsAuthorizer};
use l1_kernel_rs::worker::WorkerConfig;
use serde_json::json;

fn command(name: &str, args: &[&str]) -> Message {
    Message::new(
        "session-1",
        9,
        MessageKind::Command,
        std::collections::BTreeMap::from([
            ("name".to_owned(), json!(name)),
            ("args".to_owned(), json!(args)),
        ]),
        "trace-host-runtime",
        100.0,
    )
}

fn runtime() -> Arc<KernelRuntime> {
    Arc::new(
        KernelRuntime::new(
            AssemblySpec::new(
                "state",
                vec![
                    BootStepSpec::new("state", Vec::new()),
                    BootStepSpec::new("runtime", vec!["state".to_owned()]),
                ],
                vec![PortDescriptor::new("worker", PortKind::Worker, 1)],
            ),
            RuntimeConfig::new(2, 2, WorkerConfig::new(1, 1, 8, Duration::from_millis(20))),
        )
        .expect("valid runtime"),
    )
}

#[test]
fn composed_host_routes_and_acknowledges_one_line() {
    let host = ProtocolHostRuntime::default();
    host.register_command("hello");
    host.register_executor(|request| CapabilityResult {
        success: true,
        error: String::new(),
        capability: request.name.clone(),
        data: std::collections::BTreeMap::from([(
            "echo".to_owned(),
            l1_kernel_rs::contract::JsonValue::String("hello-result".to_owned()),
        )]),
    });
    let line = encode_message(&command("hello", &[])).expect("encode");
    let routed = host.route_line(&line).expect("route");
    assert_eq!(routed.request.seq, 9);
    assert_eq!(routed.responses.len(), 1);
    assert_eq!(routed.responses[0].payload["output"], json!("hello-result"));
    assert_eq!(routed.ack.kind, MessageKind::Ack);
    assert_eq!(routed.ack.payload["ack_seq"], json!(9));
}

#[test]
fn composed_host_converts_router_contract_errors_to_denial_and_ack() {
    let host = ProtocolHostRuntime::default();
    let event = Message::new(
        "session-1",
        4,
        MessageKind::Event,
        std::collections::BTreeMap::new(),
        "",
        100.0,
    );
    let line = encode_message(&event).expect("encode");
    let routed = host.route_line(&line).expect("transport decode");
    assert_eq!(routed.responses.len(), 1);
    assert_eq!(routed.responses[0].kind, MessageKind::Result);
    assert_eq!(routed.responses[0].payload["success"], json!(false));
    assert!(
        routed.responses[0].payload["error"]
            .as_str()
            .expect("error")
            .contains("outbound-only")
    );
    assert_eq!(routed.ack.payload["ack_seq"], json!(4));
}

#[test]
fn settings_binding_is_explicit_and_reaches_router() {
    let host = ProtocolHostRuntime::default();
    let authorizer: Arc<dyn SettingsAuthorizer> = Arc::new(StaticSettingsAuthorizer::read_only());
    assert!(host.register_settings_endpoint(runtime(), Arc::clone(&authorizer)));
    assert!(!host.register_settings_endpoint(runtime(), authorizer));
    let line = encode_message(&command("settings_get", &["llm.model"])).expect("encode");
    let routed = host.route_line(&line).expect("route");
    assert_eq!(routed.responses[0].payload["success"], json!(true));
    assert_eq!(
        routed.responses[0].payload["operation"],
        json!("settings_get")
    );
    assert_eq!(routed.ack.payload["ack_seq"], json!(9));
}

#[test]
fn settings_remain_fail_closed_without_explicit_binding() {
    let host = ProtocolHostRuntime::default();
    let line = encode_message(&command("settings_get", &[])).expect("encode");
    let routed = host.route_line(&line).expect("route");
    assert_eq!(routed.responses[0].payload["success"], json!(false));
    assert!(
        routed.responses[0].payload["error"]
            .as_str()
            .expect("error")
            .contains("endpoint is not wired")
    );
}

#[test]
fn protocol_gate_errors_remain_transport_errors() {
    let host = ProtocolHostRuntime::new(ProtocolHostRuntimeConfig {
        protocol: ProtocolHostConfig::new(8).expect("positive"),
        ..ProtocolHostRuntimeConfig::default()
    });
    let error = host.route_line("oversized").expect_err("frame bound");
    assert_eq!(
        error,
        ProtocolHostError::FrameTooLarge {
            actual_bytes: 9,
            max_bytes: 8,
        }
    );
}
