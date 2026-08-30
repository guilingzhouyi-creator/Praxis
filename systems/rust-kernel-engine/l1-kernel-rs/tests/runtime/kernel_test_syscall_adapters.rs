//! Independent tests for explicit Rust runtime syscall adapter wiring.

use std::sync::Arc;
use std::time::Duration;

use l1_kernel_rs::assembly::AssemblySpec;
use l1_kernel_rs::audit::AuditLog;
use l1_kernel_rs::boot::BootStepSpec;
use l1_kernel_rs::contract::{JsonObject, JsonValue};
use l1_kernel_rs::ports::{PortDescriptor, PortKind};
use l1_kernel_rs::runtime::{KernelRuntime, RuntimeConfig};
use l1_kernel_rs::syscall::{RegistrationOutcome, SyscallDispatcher, SyscallRequest};
use l1_kernel_rs::syscall_adapters::{
    CAPABILITY_STATUS_OPERATION, KernelSyscallAdapters, RUNTIME_OBSERVATION_OPERATION,
    RUNTIME_RECOVERY_OPERATION, RUNTIME_SNAPSHOT_OPERATION,
};
use l1_kernel_rs::worker::WorkerConfig;

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
            RuntimeConfig::new(2, 2, WorkerConfig::new(1, 1, 2, Duration::from_millis(20))),
        )
        .expect("valid runtime"),
    )
}

fn dispatch(dispatcher: &SyscallDispatcher, op: &str, args: JsonObject) -> JsonObject {
    dispatcher
        .dispatch(SyscallRequest::new(op, "l2", args))
        .to_wire()
}

#[test]
fn runtime_metadata_registration_exposes_only_defensive_reads() {
    let dispatcher = SyscallDispatcher::new(Arc::new(AuditLog::new()));
    let runtime = runtime();
    let registration =
        KernelSyscallAdapters::register_runtime_metadata(&dispatcher, Arc::clone(&runtime))
            .expect("register adapters");
    assert_eq!(registration.runtime_snapshot, RegistrationOutcome::Inserted);
    assert_eq!(
        registration.runtime_observation,
        RegistrationOutcome::Inserted
    );
    assert_eq!(registration.runtime_recovery, RegistrationOutcome::Inserted);
    assert_eq!(
        registration.capability_status,
        RegistrationOutcome::Inserted
    );

    let before = runtime.snapshot();
    let snapshot = dispatch(&dispatcher, RUNTIME_SNAPSHOT_OPERATION, JsonObject::new());
    assert_eq!(snapshot["success"], JsonValue::Bool(true));
    assert_eq!(
        snapshot.get("lifecycle"),
        Some(&JsonValue::String("halted".to_owned()))
    );
    assert_eq!(runtime.snapshot(), before);

    let observation = dispatch(
        &dispatcher,
        RUNTIME_OBSERVATION_OPERATION,
        JsonObject::new(),
    );
    assert_eq!(observation["success"], JsonValue::Bool(true));
    match observation.get("runtime") {
        Some(JsonValue::Object(runtime)) => assert_eq!(
            runtime.get("lifecycle"),
            Some(&JsonValue::String("halted".to_owned()))
        ),
        other => panic!("runtime observation missing runtime object: {other:?}"),
    }
    assert_eq!(observation.get("recovery"), Some(&JsonValue::Null));
    match observation.get("queue_metrics") {
        Some(JsonValue::Object(queue)) => assert_eq!(
            queue.get("queue_depth"),
            Some(&JsonValue::Number(serde_json::Number::from(0)))
        ),
        other => panic!("runtime observation missing queue metrics: {other:?}"),
    }

    let status = dispatch(&dispatcher, CAPABILITY_STATUS_OPERATION, JsonObject::new());
    assert_eq!(status.get("executor_wired"), Some(&JsonValue::Bool(false)));
}

#[test]
fn runtime_metadata_rejects_arguments_and_nonpersistent_recovery_fails_closed() {
    let dispatcher = SyscallDispatcher::new(Arc::new(AuditLog::new()));
    KernelSyscallAdapters::register_runtime_metadata(&dispatcher, runtime())
        .expect("register adapters");

    let invalid = dispatch(
        &dispatcher,
        RUNTIME_SNAPSHOT_OPERATION,
        JsonObject::from([("unexpected".to_owned(), JsonValue::Bool(true))]),
    );
    assert_eq!(invalid["success"], JsonValue::Bool(false));
    assert_eq!(
        invalid["error_code"],
        JsonValue::String("EINVAL".to_owned())
    );

    let recovery = dispatch(&dispatcher, RUNTIME_RECOVERY_OPERATION, JsonObject::new());
    assert_eq!(recovery["success"], JsonValue::Bool(false));
    assert_eq!(recovery["error_code"], JsonValue::String("EIO".to_owned()));
}
