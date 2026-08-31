//! Integration tests for strict Rust host bootstrap and trusted context wiring.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::contract::CapabilityResult;
use l1_kernel_rs::host_authorization::HostAuthorizationContext;
use l1_kernel_rs::host_bootstrap::{
    HostBootstrap, HostBootstrapError, HostBootstrapSpec, HostSettingsBinding,
};
use l1_kernel_rs::host_dispatch::{HostRouter, RouterConfig};
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::protocol::{Message, MessageKind};
use l1_kernel_rs::protocol_host_runtime::ProtocolHostRuntimeConfig;
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig};
use l1_kernel_rs::settings_protocol::{SettingsAuthorizer, SettingsOperation};
use l1_kernel_rs::worker::WorkerConfig;
use serde_json::json;

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

fn context() -> HostAuthorizationContext {
    HostAuthorizationContext::new("trusted-agent", "session-1", 1, true, false)
        .expect("valid context")
}

fn command(name: &str) -> Message {
    Message::new(
        "session-1",
        1,
        MessageKind::Command,
        std::collections::BTreeMap::from([("name".to_owned(), json!(name))]),
        "trace-bootstrap",
        100.0,
    )
}

#[test]
fn host_context_rejects_unbounded_identity_and_invalid_ring() {
    assert!(HostAuthorizationContext::new("", "session-1", 1, true, false).is_err());
    assert!(HostAuthorizationContext::new("trusted\0agent", "session-1", 1, true, false).is_err());
    assert!(HostAuthorizationContext::new("trusted-agent", "session-1", 0, true, false).is_err());
    assert!(HostAuthorizationContext::new("trusted-agent", "session-1", 9, true, false).is_err());
}

#[test]
fn bootstrap_preflights_all_commands_before_assembly() {
    let spec = HostBootstrapSpec::new(context())
        .with_commands(vec!["hello".to_owned(), "hello".to_owned()]);
    assert!(matches!(
        HostBootstrap::new(ProtocolHostRuntimeConfig::default(), spec),
        Err(HostBootstrapError::DuplicateCommand(command)) if command == "hello"
    ));

    let reserved = HostBootstrapSpec::new(context()).with_commands(vec!["status".to_owned()]);
    assert!(matches!(
        HostBootstrap::new(ProtocolHostRuntimeConfig::default(), reserved),
        Err(HostBootstrapError::InvalidCommand(message))
            if message.contains("reserved for system dispatch")
    ));
}

#[test]
fn strict_router_fails_closed_without_bound_context() {
    let router = HostRouter::new(RouterConfig::default().with_required_host_context());
    router.register_command("hello");
    router.register_executor(|request| CapabilityResult {
        success: true,
        error: String::new(),
        capability: request.name,
        data: Default::default(),
    });
    let error = router
        .route(command("hello"))
        .expect_err("context is required");
    assert!(
        error
            .to_string()
            .contains("trusted host authorization context")
    );
}

#[test]
fn bootstrap_binds_context_and_uses_trusted_principal() {
    let bootstrap = HostBootstrap::new(
        ProtocolHostRuntimeConfig::default(),
        HostBootstrapSpec::new(context())
            .with_commands(vec!["hello".to_owned()])
            .with_executor(|request| CapabilityResult {
                success: true,
                error: String::new(),
                capability: request.name,
                data: std::collections::BTreeMap::from([(
                    "echo".to_owned(),
                    l1_kernel_rs::contract::JsonValue::String("trusted".to_owned()),
                )]),
            }),
    )
    .expect("bootstrap");
    assert_eq!(bootstrap.report().principal, "trusted-agent");
    assert!(bootstrap.report().executor_wired);
    assert!(bootstrap.report().requires_host_context);
    let routed = bootstrap.runtime().route_message(command("hello"));
    assert_eq!(routed.responses[0].payload["output"], json!("trusted"));
    assert_eq!(
        bootstrap
            .runtime()
            .router()
            .authorization_context("session-1"),
        Some(context())
    );
}

#[test]
fn trusted_ring_cannot_be_escalated_by_wire_metadata() {
    let bootstrap = HostBootstrap::new(
        ProtocolHostRuntimeConfig::default(),
        HostBootstrapSpec::new(context()).with_executor(|request| CapabilityResult {
            success: true,
            error: String::new(),
            capability: request.name,
            data: Default::default(),
        }),
    )
    .expect("bootstrap");
    let mut payload = std::collections::BTreeMap::from([
        ("name".to_owned(), json!("status")),
        ("ring".to_owned(), json!(8)),
    ]);
    payload.insert("danger".to_owned(), json!(1));
    let routed = bootstrap.runtime().route_message(Message::new(
        "session-1",
        3,
        MessageKind::Command,
        payload,
        "trace-ring",
        102.0,
    ));
    assert_eq!(routed.responses[0].payload["success"], json!(true));
}

#[derive(Default)]
struct ContextRecordingAuthorizer {
    contexts: Mutex<Vec<ContextAuthorizationCall>>,
}

type ContextAuthorizationCall = (String, u8, bool, bool, SettingsOperation, Option<String>);

impl SettingsAuthorizer for ContextRecordingAuthorizer {
    fn authorize(
        &self,
        _agent_id: &str,
        _operation: SettingsOperation,
        _key: Option<&str>,
    ) -> Result<(), String> {
        Err("legacy principal-only authorization is not accepted".to_owned())
    }

    fn authorize_context(
        &self,
        context: &HostAuthorizationContext,
        operation: SettingsOperation,
        key: Option<&str>,
    ) -> Result<(), String> {
        self.contexts.lock().expect("authorizer lock").push((
            context.session_id.clone(),
            context.ring,
            context.identity_verified,
            context.engineering_debug,
            operation,
            key.map(str::to_owned),
        ));
        Ok(())
    }
}

#[test]
fn bootstrap_settings_are_authorized_with_trusted_context() {
    let authorizer = Arc::new(ContextRecordingAuthorizer::default());
    let bootstrap = HostBootstrap::new(
        ProtocolHostRuntimeConfig::default(),
        HostBootstrapSpec::new(
            HostAuthorizationContext::new("engineer", "session-1", 2, true, true).expect("context"),
        )
        .with_settings(HostSettingsBinding::new(
            runtime(),
            Arc::clone(&authorizer) as Arc<dyn SettingsAuthorizer>,
        )),
    )
    .expect("bootstrap");
    let routed = bootstrap.runtime().route_message(Message::new(
        "session-1",
        2,
        MessageKind::Command,
        std::collections::BTreeMap::from([
            ("name".to_owned(), json!("settings_get")),
            ("args".to_owned(), json!(["llm.model"])),
        ]),
        "trace-settings",
        101.0,
    ));
    assert_eq!(routed.responses[0].payload["success"], json!(true));
    assert_eq!(
        authorizer
            .contexts
            .lock()
            .expect("authorizer lock")
            .as_slice(),
        &[(
            "session-1".to_owned(),
            2,
            true,
            true,
            SettingsOperation::Read,
            Some("llm.model".to_owned()),
        )]
    );
}

#[test]
fn strict_bootstrap_rejects_unverified_high_ring_before_dispatch() {
    let bootstrap = HostBootstrap::new(
        ProtocolHostRuntimeConfig::default(),
        HostBootstrapSpec::new(
            HostAuthorizationContext::new("unverified", "session-1", 2, false, false)
                .expect("bounded context"),
        )
        .with_commands(vec!["hello".to_owned()])
        .with_executor(|request| CapabilityResult {
            success: true,
            error: String::new(),
            capability: request.name,
            data: Default::default(),
        }),
    )
    .expect("bootstrap context itself is structurally valid");
    let routed = bootstrap.runtime().route_message(command("hello"));
    assert!(
        routed.responses[0].payload["error"]
            .as_str()
            .expect("denial")
            .contains("verified host identity")
    );
}

#[test]
fn bootstrap_without_optional_authorities_remains_fail_closed() {
    let bootstrap = HostBootstrap::new(
        ProtocolHostRuntimeConfig::default(),
        HostBootstrapSpec::new(context()).with_commands(vec!["hello".to_owned()]),
    )
    .expect("bootstrap");
    assert!(!bootstrap.report().executor_wired);
    assert!(!bootstrap.report().settings_wired);
    let routed = bootstrap.runtime().route_message(command("hello"));
    assert_eq!(routed.responses[0].payload["success"], json!(false));
    assert!(
        routed.responses[0].payload["output"]
            .as_str()
            .expect("output")
            .contains("fail-closed")
    );
}
