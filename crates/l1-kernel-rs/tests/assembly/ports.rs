//! Independent port-value and registry mechanism tests for the Rust kernel.

use l1_kernel_rs::contract::JsonValue;
use l1_kernel_rs::ports::{
    Endpoint, InputActivitySnapshot, InputActivityState, Message, PortDescriptor, PortKind,
    PortRegistry, PortRegistryError, PortResult,
};
use serde_json::json;

#[test]
fn registry_is_deterministic_and_locked() {
    let mut registry = PortRegistry::new();
    registry
        .register(PortDescriptor::new("process", PortKind::Process, 1), false)
        .expect("process");
    registry
        .register(PortDescriptor::new("storage", PortKind::Storage, 1), false)
        .expect("storage");
    assert!(matches!(
        registry.register(PortDescriptor::new("process", PortKind::Process, 1), false),
        Err(PortRegistryError::Duplicate { .. })
    ));
    registry.lock();
    assert!(matches!(
        registry.register(PortDescriptor::new("lock", PortKind::Lock, 1), false),
        Err(PortRegistryError::Locked)
    ));
    registry
        .register(
            PortDescriptor::new("process", PortKind::Process, 2)
                .with_metadata("native", JsonValue::Bool(true)),
            true,
        )
        .expect("explicit replacement");
    assert_eq!(registry.snapshot()[0].contract_version, 2);
}

#[test]
fn values_validate_without_side_effects() {
    assert!(Endpoint::new("127.0.0.1:9000", "tcp").validate().is_ok());
    assert!(Endpoint::new("", "tcp").validate().is_err());
    let message = Message {
        message_type: "message".to_owned(),
        source: "a".to_owned(),
        target: "b".to_owned(),
        payload: JsonValue::Object(Default::default()),
        timestamp: 1.0,
        locale: "en".to_owned(),
        headers: Default::default(),
    };
    assert!(message.validate().is_ok());
    assert!(
        InputActivitySnapshot {
            state: InputActivityState::Idle,
            keyboard_active: false,
            pointer_active: false,
            last_activity_at: 1.0,
            idle_seconds: 2.0,
            source: "noop".to_owned(),
            permission: "unavailable".to_owned(),
        }
        .validate()
        .is_ok()
    );
    assert_eq!(
        PortResult::ok_with("ready", JsonValue::Bool(true)).data["ready"],
        JsonValue::Bool(true)
    );
    assert_eq!(
        serde_json::to_value(PortResult::fail("no adapter")).expect("json"),
        json!({"success": false, "error": "no adapter", "data": {}})
    );
}
