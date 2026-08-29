//! Independent tests for the Rust unified syscall dispatch boundary.

use std::sync::Arc;
use std::thread;

use l1_kernel_rs::audit::AuditLog;
use l1_kernel_rs::contract::{JsonObject, JsonValue};
use l1_kernel_rs::syscall::{
    RegistrationOutcome, SyscallConfig, SyscallDispatcher, SyscallFailure,
    SyscallRegistrationError, SyscallRequest,
};

fn args(entries: &[(&str, JsonValue)]) -> JsonObject {
    entries
        .iter()
        .map(|(key, value)| ((*key).to_owned(), value.clone()))
        .collect()
}

#[test]
fn registration_is_bounded_sorted_and_replacement_is_explicit() {
    let dispatcher = SyscallDispatcher::with_config(
        SyscallConfig {
            max_operations: 1,
            ..SyscallConfig::default()
        },
        Arc::new(AuditLog::new()),
    )
    .expect("valid config");
    assert_eq!(
        dispatcher
            .register("zeta", |_| Ok(JsonObject::new()))
            .expect("first registration"),
        RegistrationOutcome::Inserted
    );
    assert_eq!(
        dispatcher
            .register("zeta", |_| Ok(JsonObject::new()))
            .expect("replacement"),
        RegistrationOutcome::Replaced
    );
    assert_eq!(
        dispatcher.register("alpha", |_| Ok(JsonObject::new())),
        Err(SyscallRegistrationError::Full)
    );
    assert_eq!(dispatcher.registered_operations(), vec!["zeta".to_owned()]);
    assert!(dispatcher.unregister("zeta"));
    assert!(!dispatcher.unregister("zeta"));
}

#[test]
fn request_validation_and_unknown_operations_fail_closed_and_audit() {
    let audit = Arc::new(AuditLog::new());
    let dispatcher = SyscallDispatcher::new(Arc::clone(&audit));
    let unknown = dispatcher.dispatch(SyscallRequest::new(
        "process.list",
        "agent-1",
        JsonObject::new(),
    ));
    assert!(!unknown.success);
    assert_eq!(unknown.error_code, "EINVAL");
    let invalid = dispatcher.dispatch(SyscallRequest::new(" ", "agent-1", JsonObject::new()));
    assert!(!invalid.success);
    assert_eq!(invalid.error_code, "EINVAL");
    let stats = dispatcher.stats();
    assert_eq!(stats.total, 2);
    assert_eq!(stats.failures, 2);
    assert_eq!(stats.audit_entries, 2);
    assert_eq!(audit.query(10, None).len(), 2);
}

#[test]
fn handler_data_is_flattened_without_allowing_response_forgery() {
    let dispatcher = SyscallDispatcher::default();
    dispatcher
        .register("echo", |request| {
            Ok(args(&[
                ("seen", JsonValue::String(request.agent_id.clone())),
                ("success", JsonValue::Bool(false)),
            ]))
        })
        .expect("register");
    let response = dispatcher.dispatch(SyscallRequest::new(
        "echo",
        "agent-2",
        args(&[("value", JsonValue::String("ok".to_owned()))]),
    ));
    assert!(response.success);
    assert_eq!(
        response.data.get("seen"),
        Some(&JsonValue::String("agent-2".to_owned()))
    );
    assert_eq!(
        response.to_wire().get("success"),
        Some(&JsonValue::Bool(true))
    );
}

#[test]
fn handler_errors_and_panics_are_structured_and_counted() {
    let dispatcher = SyscallDispatcher::default();
    dispatcher
        .register("error", |_| {
            Err(SyscallFailure::new("E_CUSTOM", "rejected by adapter"))
        })
        .expect("register error");
    dispatcher
        .register("panic", |_| -> Result<_, SyscallFailure> { panic!("boom") })
        .expect("register panic");
    let error = dispatcher.dispatch(SyscallRequest::new("error", "agent-3", JsonObject::new()));
    let panic = dispatcher.dispatch(SyscallRequest::new("panic", "agent-3", JsonObject::new()));
    assert_eq!(error.error_code, "E_CUSTOM");
    assert_eq!(panic.error_code, "EFAULT");
    let stats = dispatcher.stats();
    assert_eq!(stats.total, 2);
    assert_eq!(stats.failures, 2);
    assert_eq!(stats.handler_panics, 1);
}

#[test]
fn concurrent_dispatch_preserves_total_and_audit_count() {
    let audit = Arc::new(AuditLog::new());
    let dispatcher = Arc::new(SyscallDispatcher::new(Arc::clone(&audit)));
    dispatcher
        .register("count", |_| Ok(JsonObject::new()))
        .expect("register");
    let workers = (0..4)
        .map(|worker| {
            let dispatcher = Arc::clone(&dispatcher);
            thread::spawn(move || {
                for index in 0..64 {
                    let response = dispatcher.dispatch(SyscallRequest::new(
                        "count",
                        format!("agent-{worker}"),
                        args(&[("index", JsonValue::Number(index.into()))]),
                    ));
                    assert!(response.success);
                }
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().expect("worker joined");
    }
    assert_eq!(dispatcher.stats().total, 256);
    assert_eq!(dispatcher.stats().failures, 0);
    assert_eq!(audit.query(300, None).len(), 256);
}

#[test]
fn invalid_nested_arguments_are_rejected_before_handler() {
    let dispatcher = SyscallDispatcher::default();
    dispatcher
        .register("nested", |_| Ok(JsonObject::new()))
        .expect("register");
    let response = dispatcher.dispatch(SyscallRequest::new(
        "nested",
        "agent",
        args(&[(
            "payload",
            JsonValue::Object(args(&[("bad\0key", JsonValue::String("value".to_owned()))])),
        )]),
    ));
    assert_eq!(response.error_code, "EINVAL");
    assert_eq!(dispatcher.stats().total, 1);
    assert_eq!(dispatcher.stats().failures, 1);
}
