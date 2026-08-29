//! Independent tests for the Rust unified syscall dispatch boundary.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
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
fn lookup_index_preserves_deterministic_names_across_replacement_and_removal() {
    let dispatcher = SyscallDispatcher::default();
    dispatcher
        .register("zeta", |_| Ok(JsonObject::new()))
        .expect("register zeta");
    dispatcher
        .register("alpha", |_| Ok(JsonObject::new()))
        .expect("register alpha");
    assert_eq!(
        dispatcher.registered_operations(),
        vec!["alpha".to_owned(), "zeta".to_owned()]
    );

    assert_eq!(
        dispatcher
            .register("alpha", |_| {
                Ok(JsonObject::from([(
                    "replacement".to_owned(),
                    JsonValue::Bool(true),
                )]))
            })
            .expect("replace alpha"),
        RegistrationOutcome::Replaced
    );
    let response = dispatcher.dispatch(SyscallRequest::new("alpha", "agent", JsonObject::new()));
    assert_eq!(
        response.data.get("replacement"),
        Some(&JsonValue::Bool(true))
    );
    assert_eq!(
        dispatcher.registered_operations(),
        vec!["alpha".to_owned(), "zeta".to_owned()]
    );

    assert!(dispatcher.unregister("alpha"));
    assert_eq!(dispatcher.registered_operations(), vec!["zeta".to_owned()]);
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

#[test]
fn oversized_arguments_fail_before_handler_without_retaining_payload() {
    let dispatcher = SyscallDispatcher::with_config(
        SyscallConfig {
            max_argument_bytes: 16,
            ..SyscallConfig::default()
        },
        Arc::new(AuditLog::new()),
    )
    .expect("valid config");
    let invoked = Arc::new(AtomicBool::new(false));
    let invoked_by_handler = Arc::clone(&invoked);
    dispatcher
        .register("bounded", move |_| {
            invoked_by_handler.store(true, Ordering::Relaxed);
            Ok(JsonObject::new())
        })
        .expect("register bounded");

    let response = dispatcher.dispatch(SyscallRequest::new(
        "bounded",
        "agent",
        args(&[(
            "payload",
            JsonValue::String("this payload exceeds the bound".to_owned()),
        )]),
    ));
    assert_eq!(response.error_code, "EINVAL");
    assert!(response.error.contains("arguments exceed 16 bytes"));
    assert!(!invoked.load(Ordering::Relaxed));
}

#[test]
fn batch_registration_is_atomic_when_capacity_is_insufficient() {
    let dispatcher = SyscallDispatcher::with_config(
        SyscallConfig {
            max_operations: 2,
            ..SyscallConfig::default()
        },
        Arc::new(AuditLog::new()),
    )
    .expect("valid config");
    let result = dispatcher.register_batch([
        (
            "first".to_owned(),
            Arc::new(|_: &SyscallRequest| Ok(JsonObject::new()))
                as l1_kernel_rs::syscall::SyscallHandler,
        ),
        (
            "second".to_owned(),
            Arc::new(|_: &SyscallRequest| Ok(JsonObject::new()))
                as l1_kernel_rs::syscall::SyscallHandler,
        ),
        (
            "third".to_owned(),
            Arc::new(|_: &SyscallRequest| Ok(JsonObject::new()))
                as l1_kernel_rs::syscall::SyscallHandler,
        ),
    ]);
    assert_eq!(result, Err(SyscallRegistrationError::Full));
    assert!(dispatcher.registered_operations().is_empty());
}
