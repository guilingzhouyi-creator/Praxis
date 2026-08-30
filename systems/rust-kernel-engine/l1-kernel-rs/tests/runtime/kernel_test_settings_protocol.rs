//! Settings protocol integration tests for host authorization and snapshots.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::host_dispatch::{HostRouter, RouterConfig};
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::protocol::{Message, MessageKind};
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig};
use l1_kernel_rs::settings_protocol::{
    SettingsAuthorizer, SettingsOperation, StaticSettingsAuthorizer,
};
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

fn command(name: &str, args: &[&str]) -> Message {
    Message::new(
        "session-1",
        1,
        MessageKind::Command,
        std::collections::BTreeMap::from([
            ("name".to_owned(), json!(name)),
            ("args".to_owned(), json!(args)),
        ]),
        "trace-settings",
        100.0,
    )
}

fn endpoint(router: &HostRouter, authorizer: Arc<dyn SettingsAuthorizer>) -> Arc<KernelRuntime> {
    let runtime = runtime();
    assert!(router.register_settings_endpoint(Arc::clone(&runtime), authorizer));
    runtime
}

#[test]
fn unconfigured_settings_endpoint_fails_closed_as_result() {
    let router = HostRouter::new(RouterConfig::default());
    let responses = router
        .route(command("settings_get", &[]))
        .expect("semantic rejection is a result envelope");
    assert_eq!(responses.len(), 1);
    assert_eq!(responses[0].payload["success"], json!(false));
    assert!(
        responses[0].payload["error"]
            .as_str()
            .expect("error text")
            .contains("endpoint is not wired")
    );
}

#[test]
fn settings_get_returns_versioned_rust_snapshot() {
    let router = HostRouter::new(RouterConfig::default());
    let runtime = endpoint(&router, Arc::new(StaticSettingsAuthorizer::read_only()));
    let responses = router
        .route(command("settings_get", &["llm.model"]))
        .expect("read");
    let payload = &responses[0].payload;
    assert_eq!(payload["success"], json!(true));
    assert_eq!(payload["operation"], json!("settings_get"));
    assert_eq!(payload["source"], json!("fallback"));
    assert_eq!(payload["revision"], json!(0));
    assert_eq!(payload["key"], json!("llm.model"));
    assert_eq!(payload["value"], json!("codellama:7b"));
    assert_eq!(payload["values"]["llm.model"], json!("codellama:7b"));
    assert_eq!(
        payload["values"].as_object().expect("values object").len(),
        1
    );
    assert_eq!(
        runtime.settings().get("llm.model").expect("settings read"),
        Some(json!("codellama:7b"))
    );
    let audit = router
        .audit()
        .query(10, None)
        .into_iter()
        .find(|row| row.op == "dispatch.settings" && row.success)
        .expect("settings audit row");
    assert!(audit.detail.contains("command=settings_get"));
}

#[test]
fn settings_set_requires_host_injected_write_authorization() {
    let router = HostRouter::new(RouterConfig::default());
    let runtime = endpoint(&router, Arc::new(StaticSettingsAuthorizer::read_only()));
    let responses = router
        .route(command(
            "settings_set",
            &["llm.model", r#""blocked-model""#],
        ))
        .expect("authorization denial is a result envelope");
    assert_eq!(responses[0].payload["success"], json!(false));
    assert!(
        responses[0].payload["error"]
            .as_str()
            .expect("error text")
            .contains("authorization denied")
    );
    assert_eq!(
        runtime.settings().get("llm.model").expect("settings read"),
        Some(json!("codellama:7b"))
    );
}

#[test]
fn settings_set_updates_runtime_and_advances_revision() {
    let router = HostRouter::new(RouterConfig::default());
    let runtime = endpoint(&router, Arc::new(StaticSettingsAuthorizer::read_write()));
    let responses = router
        .route(command("settings_set", &["llm.model", r#""rust-model""#]))
        .expect("write");
    let payload = &responses[0].payload;
    assert_eq!(payload["success"], json!(true));
    assert_eq!(payload["operation"], json!("settings_set"));
    assert_eq!(payload["revision"], json!(1));
    assert_eq!(payload["value"], json!("rust-model"));
    assert_eq!(
        runtime.settings().get("llm.model").expect("settings read"),
        Some(json!("rust-model"))
    );

    let read = router
        .route(command("settings_get", &["llm.model"]))
        .expect("read after write");
    assert_eq!(read[0].payload["revision"], json!(1));
    assert_eq!(read[0].payload["value"], json!("rust-model"));
}

#[test]
fn settings_set_rejects_bad_argument_shape_without_mutation() {
    let router = HostRouter::new(RouterConfig::default());
    let runtime = endpoint(&router, Arc::new(StaticSettingsAuthorizer::read_write()));
    for args in [&["llm.model"][..], &["llm.model", "not-json", "extra"][..]] {
        let responses = router
            .route(command("settings_set", args))
            .expect("bad command shape is a result envelope");
        assert_eq!(responses[0].payload["success"], json!(false));
    }
    let invalid_json = router
        .route(command("settings_set", &["llm.model", "not-json"]))
        .expect("invalid json is a result envelope");
    assert_eq!(invalid_json[0].payload["success"], json!(false));
    assert_eq!(
        runtime.settings().get("llm.model").expect("settings read"),
        Some(json!("codellama:7b"))
    );
}

#[derive(Default)]
struct RecordingAuthorizer {
    calls: Mutex<Vec<(String, SettingsOperation, Option<String>)>>,
}

impl SettingsAuthorizer for RecordingAuthorizer {
    fn authorize(
        &self,
        agent_id: &str,
        operation: SettingsOperation,
        key: Option<&str>,
    ) -> Result<(), String> {
        self.calls.lock().expect("authorizer lock").push((
            agent_id.to_owned(),
            operation,
            key.map(str::to_owned),
        ));
        Ok(())
    }
}

#[test]
fn settings_authorizer_receives_host_identity_and_key_only() {
    let router = HostRouter::new(RouterConfig::default());
    let authorizer = Arc::new(RecordingAuthorizer::default());
    endpoint(
        &router,
        Arc::clone(&authorizer) as Arc<dyn SettingsAuthorizer>,
    );
    router
        .route(Message::new(
            "session-1",
            1,
            MessageKind::Control,
            std::collections::BTreeMap::from([
                ("op".to_owned(), json!("attach")),
                ("session_id".to_owned(), json!("session-1")),
            ]),
            "",
            100.0,
        ))
        .expect("attach");
    router
        .route(command(
            "settings_set",
            &["llm.model", r#""audited-model""#],
        ))
        .expect("write");
    let calls = authorizer.calls.lock().expect("authorizer lock").clone();
    assert_eq!(
        calls,
        vec![(
            "session-1".to_owned(),
            SettingsOperation::Write,
            Some("llm.model".to_owned())
        )]
    );
}
