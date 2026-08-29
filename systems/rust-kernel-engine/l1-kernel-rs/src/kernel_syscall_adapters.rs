//! Explicit read-only syscall adapters for Rust-owned runtime metadata.
//!
//! These adapters are opt-in host wiring: they expose snapshots to a future
//! L2/TypeScript bridge without moving execution authority into the syscall
//! table. Capability invocation remains behind [`KernelRuntime::submit_gated`]
//! and is intentionally not registered here.

use std::sync::Arc;

use serde::Serialize;

use crate::contract::JsonObject;
use crate::runtime::KernelRuntime;
use crate::syscall::{
    RegistrationOutcome, SyscallDispatcher, SyscallFailure, SyscallHandler,
    SyscallRegistrationError, SyscallRequest,
};

/// Operation name for a Rust runtime metadata snapshot.
pub const RUNTIME_SNAPSHOT_OPERATION: &str = "kernel.runtime.snapshot";
/// Operation name for a side-effect-free recovery decision read.
pub const RUNTIME_RECOVERY_OPERATION: &str = "kernel.runtime.recovery";
/// Operation name for capability-authority wiring status.
pub const CAPABILITY_STATUS_OPERATION: &str = "kernel.capability.status";

/// Registration results for the independent runtime metadata adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuntimeAdapterRegistration {
    /// Outcome for the runtime snapshot operation.
    pub runtime_snapshot: RegistrationOutcome,
    /// Outcome for the recovery decision operation.
    pub runtime_recovery: RegistrationOutcome,
    /// Outcome for the capability wiring status operation.
    pub capability_status: RegistrationOutcome,
}

/// Host-owned registration helpers for safe runtime observations.
pub struct KernelSyscallAdapters;

impl KernelSyscallAdapters {
    /// Register the complete read-only runtime metadata surface.
    ///
    /// The caller chooses when this surface is visible. Every handler accepts
    /// only an empty argument object and returns a defensive JSON snapshot.
    /// No handler submits work, mutates state, or invokes a capability.
    pub fn register_runtime_metadata(
        dispatcher: &SyscallDispatcher,
        runtime: Arc<KernelRuntime>,
    ) -> Result<RuntimeAdapterRegistration, SyscallRegistrationError> {
        let snapshot_runtime = Arc::clone(&runtime);
        let recovery_runtime = Arc::clone(&runtime);
        let capability = runtime.capability_authority();
        let entries: [(String, SyscallHandler); 3] = [
            (
                RUNTIME_SNAPSHOT_OPERATION.to_owned(),
                Arc::new(move |request: &SyscallRequest| {
                    require_empty_args(request)?;
                    encode(&snapshot_runtime.snapshot())
                }) as SyscallHandler,
            ),
            (
                RUNTIME_RECOVERY_OPERATION.to_owned(),
                Arc::new(move |request: &SyscallRequest| {
                    require_empty_args(request)?;
                    let decision = recovery_runtime.recovery_decision().map_err(|_| {
                        SyscallFailure::new("EIO", "runtime recovery decision unavailable")
                    })?;
                    encode(&decision)
                }) as SyscallHandler,
            ),
            (
                CAPABILITY_STATUS_OPERATION.to_owned(),
                Arc::new(move |request: &SyscallRequest| {
                    require_empty_args(request)?;
                    Ok(JsonObject::from([(
                        "executor_wired".to_owned(),
                        crate::contract::JsonValue::Bool(capability.has_executor()),
                    )]))
                }) as SyscallHandler,
            ),
        ];
        let [runtime_snapshot, runtime_recovery, capability_status] =
            dispatcher.register_batch(entries)?;

        Ok(RuntimeAdapterRegistration {
            runtime_snapshot,
            runtime_recovery,
            capability_status,
        })
    }
}

/// Require the fixed read-only adapter argument shape.
fn require_empty_args(request: &SyscallRequest) -> Result<(), SyscallFailure> {
    if request.args.is_empty() {
        Ok(())
    } else {
        Err(SyscallFailure::new(
            "EINVAL",
            "runtime metadata operations do not accept arguments",
        ))
    }
}

/// Convert a serializable Rust value into the language-neutral JSON object.
fn encode<T: Serialize>(value: &T) -> Result<JsonObject, SyscallFailure> {
    let encoded = serde_json::to_value(value)
        .map_err(|_| SyscallFailure::new("EFAULT", "runtime metadata serialization failed"))?;
    serde_json::from_value(encoded)
        .map_err(|_| SyscallFailure::new("EFAULT", "runtime metadata is not an object"))
}
