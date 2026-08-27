//! Independent capability-authority tests for the Rust kernel.

use std::collections::BTreeMap;
use std::sync::Arc;

use l1_kernel_rs::capability::{
    CapabilityAuthority, get_capability_authority, reset_capability_authority,
};
use l1_kernel_rs::contract::{CapabilityRequest, CapabilityResult, JsonObject, JsonValue};

fn request() -> CapabilityRequest {
    CapabilityRequest {
        agent_id: "agent-a".to_owned(),
        name: "read_file".to_owned(),
        args: JsonObject::from([("path".to_owned(), JsonValue::String("/tmp/x".to_owned()))]),
        domain: "d".to_owned(),
        nature: "n".to_owned(),
        interactive: true,
    }
}

#[test]
fn unwired_invocation_fails_closed_and_is_audited() {
    let authority = CapabilityAuthority::new();
    let result = authority.invoke(request());
    assert!(!result.success);
    assert!(result.error.contains("fail-closed"));
    let rows = authority.audit().query(10, Some("agent-a"));
    assert_eq!(rows.len(), 1);
    assert!(!rows[0].success);
}

#[test]
fn wired_executor_receives_request_and_audits_result() {
    let authority = CapabilityAuthority::new();
    authority.register_executor(|request| CapabilityResult {
        success: true,
        error: String::new(),
        capability: request.name,
        data: JsonObject::from([(
            "result".to_owned(),
            JsonValue::Object(BTreeMap::from([("ok".to_owned(), JsonValue::Bool(true))])),
        )]),
    });
    let result = authority.invoke(request());
    assert!(result.success);
    assert_eq!(
        result.data["result"],
        JsonValue::Object(BTreeMap::from([("ok".to_owned(), JsonValue::Bool(true))]))
    );
    assert!(authority.audit().query(10, Some("agent-a"))[0].success);
}

#[test]
fn executor_failure_and_panic_are_structured() {
    let authority = CapabilityAuthority::new();
    authority.register_executor(|_| CapabilityResult {
        success: false,
        error: "nope".to_owned(),
        capability: String::new(),
        data: Default::default(),
    });
    let failed = authority.invoke(request());
    assert_eq!(failed.error, "nope");
    authority.register_executor(|_| panic!("boom"));
    let panicked = authority.invoke(request());
    assert_eq!(panicked.error, "capability executor panicked");
}

#[test]
fn global_authority_can_be_reset() {
    let first = get_capability_authority();
    first.register_executor(|_| CapabilityResult::unwired("x"));
    reset_capability_authority();
    assert!(!get_capability_authority().has_executor());
    let _ = Arc::strong_count(&first);
}
