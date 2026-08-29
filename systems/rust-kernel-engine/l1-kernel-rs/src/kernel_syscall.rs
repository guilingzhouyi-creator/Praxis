//! Rust-native unified syscall dispatch boundary for the clean-break kernel.
//!
//! The dispatcher owns request validation, bounded handler registration,
//! panic containment, audit publication, and dispatch counters. Concrete
//! operations are injected by a host adapter; this module never discovers
//! Python services, bypasses the capability authority, or selects runtime
//! defaults. The boundary deliberately keeps handler data in a deterministic
//! JSON object so a later TypeScript/L2 bridge can consume the same record
//! without importing Rust implementation types.

use std::collections::BTreeMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::audit::AuditLog;
use crate::contract::{JsonObject, JsonValue};

/// Version of the Rust syscall request/response contract.
pub const SYSCALL_CONTRACT_VERSION: u32 = 1;
/// Maximum UTF-8 bytes retained for one operation name.
pub const SYSCALL_MAX_OPERATION_BYTES: usize = 128;
/// Maximum UTF-8 bytes retained for one caller identity.
pub const SYSCALL_MAX_AGENT_ID_BYTES: usize = 256;
/// Maximum serialized argument object accepted by one request.
pub const SYSCALL_MAX_ARGUMENT_BYTES: usize = 1 << 20;
/// Maximum registered operations retained by one dispatcher.
pub const SYSCALL_MAX_OPERATIONS: usize = 256;

/// Stable failure returned by an injected syscall handler.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyscallFailure {
    /// Machine-readable failure code.
    pub code: String,
    /// Bounded human-readable failure message.
    pub message: String,
}

impl SyscallFailure {
    /// Construct a syscall failure from a code and message.
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }

    fn invalid(message: impl Into<String>) -> Self {
        Self::new("EINVAL", message)
    }
}

/// Request passed to one registered syscall handler.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SyscallRequest {
    /// Fully-qualified operation name, for example `process.list`.
    pub op: String,
    /// Boundary-authenticated caller identity.
    pub agent_id: String,
    /// Deterministic JSON arguments supplied by the caller.
    #[serde(default)]
    pub args: JsonObject,
}

impl SyscallRequest {
    /// Build a request without performing side effects.
    pub fn new(op: impl Into<String>, agent_id: impl Into<String>, args: JsonObject) -> Self {
        Self {
            op: op.into(),
            agent_id: agent_id.into(),
            args,
        }
    }

    fn validate(&self, config: SyscallConfig) -> Result<(), SyscallFailure> {
        validate_text(&self.op, "operation", config.max_operation_bytes, false)?;
        validate_text(&self.agent_id, "agent_id", config.max_agent_id_bytes, false)?;
        validate_json_object(&self.args)?;
        let encoded = serde_json::to_vec(&self.args).map_err(|error| {
            SyscallFailure::invalid(format!("arguments are not serializable: {error}"))
        })?;
        if encoded.len() > config.max_argument_bytes {
            return Err(SyscallFailure::invalid(format!(
                "arguments exceed {} bytes",
                config.max_argument_bytes
            )));
        }
        Ok(())
    }
}

/// Response returned by the dispatcher before a wire adapter flattens it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SyscallResponse {
    /// Whether the handler accepted the request.
    pub success: bool,
    /// Human-readable failure text, empty on success.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub error: String,
    /// Machine-readable failure code, empty on success.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub error_code: String,
    /// Handler-owned result values.
    #[serde(default)]
    pub data: JsonObject,
}

impl SyscallResponse {
    /// Build a successful response.
    pub fn success(data: JsonObject) -> Self {
        Self {
            success: true,
            error: String::new(),
            error_code: String::new(),
            data,
        }
    }

    /// Build a failure response.
    pub fn failure(failure: SyscallFailure) -> Self {
        Self {
            success: false,
            error: failure.message,
            error_code: failure.code,
            data: JsonObject::new(),
        }
    }

    /// Flatten the response into the retained Python-style top-level shape.
    ///
    /// Handler data is copied first; authoritative response fields overwrite
    /// any colliding handler keys so a handler cannot forge `success`.
    pub fn to_wire(&self) -> JsonObject {
        let mut wire = self.data.clone();
        wire.insert("success".to_owned(), JsonValue::Bool(self.success));
        if !self.error.is_empty() {
            wire.insert("error".to_owned(), JsonValue::String(self.error.clone()));
        }
        if !self.error_code.is_empty() {
            wire.insert(
                "error_code".to_owned(),
                JsonValue::String(self.error_code.clone()),
            );
        }
        wire
    }
}

/// Dispatcher configuration with explicit bounds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct SyscallConfig {
    /// Maximum registered handlers.
    pub max_operations: usize,
    /// Maximum operation-name bytes.
    pub max_operation_bytes: usize,
    /// Maximum caller-id bytes.
    pub max_agent_id_bytes: usize,
    /// Maximum serialized argument bytes.
    pub max_argument_bytes: usize,
}

impl Default for SyscallConfig {
    /// Build the default bounded configuration.
    fn default() -> Self {
        Self {
            max_operations: SYSCALL_MAX_OPERATIONS,
            max_operation_bytes: SYSCALL_MAX_OPERATION_BYTES,
            max_agent_id_bytes: SYSCALL_MAX_AGENT_ID_BYTES,
            max_argument_bytes: SYSCALL_MAX_ARGUMENT_BYTES,
        }
    }
}

impl SyscallConfig {
    /// Validate configuration before a dispatcher is created.
    pub fn validate(self) -> Result<(), SyscallConfigError> {
        if self.max_operations == 0 {
            return Err(SyscallConfigError::ZeroBound("max_operations"));
        }
        if self.max_operation_bytes == 0 {
            return Err(SyscallConfigError::ZeroBound("max_operation_bytes"));
        }
        if self.max_agent_id_bytes == 0 {
            return Err(SyscallConfigError::ZeroBound("max_agent_id_bytes"));
        }
        if self.max_argument_bytes == 0 {
            return Err(SyscallConfigError::ZeroBound("max_argument_bytes"));
        }
        Ok(())
    }
}

/// Configuration failure returned before a dispatcher is usable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SyscallConfigError {
    /// A bounded field was configured as zero.
    ZeroBound(&'static str),
}

impl std::fmt::Display for SyscallConfigError {
    /// Render a stable configuration diagnostic.
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ZeroBound(field) => write!(formatter, "{field} must be greater than zero"),
        }
    }
}

impl std::error::Error for SyscallConfigError {}

/// Registration failure at the syscall table boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum SyscallRegistrationError {
    /// Operation name is empty, too long, or contains NUL.
    InvalidName,
    /// The configured table has no free slot.
    Full,
}

impl std::fmt::Display for SyscallRegistrationError {
    /// Render a stable registration diagnostic.
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidName => formatter.write_str("invalid syscall name"),
            Self::Full => formatter.write_str("syscall registry is full"),
        }
    }
}

impl std::error::Error for SyscallRegistrationError {}

/// Whether a registration inserted or replaced one operation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RegistrationOutcome {
    /// No previous handler existed.
    Inserted,
    /// An adapter explicitly replaced a previous handler.
    Replaced,
}

/// Function accepted as one host-injected syscall implementation.
pub type SyscallHandler =
    Arc<dyn Fn(&SyscallRequest) -> Result<JsonObject, SyscallFailure> + Send + Sync + 'static>;

#[derive(Default)]
struct DispatcherState {
    handlers: BTreeMap<String, SyscallHandler>,
}

/// Runtime counters exposed without exposing handler internals.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct SyscallStats {
    /// Number of dispatch attempts, including rejected requests.
    pub total: u64,
    /// Number of failed responses.
    pub failures: u64,
    /// Number of handler panics converted to `EFAULT`.
    pub handler_panics: u64,
    /// Number of registered operations.
    pub registered_operations: usize,
    /// Number of in-memory audit rows retained.
    pub audit_entries: usize,
    /// Average handler/validation latency in microseconds.
    pub average_latency_us: f64,
}

/// Unique Rust syscall boundary with bounded registration and audit.
pub struct SyscallDispatcher {
    config: SyscallConfig,
    state: Mutex<DispatcherState>,
    audit: Arc<AuditLog>,
    total: AtomicU64,
    failures: AtomicU64,
    handler_panics: AtomicU64,
    latency_ns: AtomicU64,
}

impl SyscallDispatcher {
    /// Create a dispatcher with default bounds and a caller-owned audit log.
    pub fn new(audit: Arc<AuditLog>) -> Self {
        Self::with_config(SyscallConfig::default(), audit)
            .expect("default syscall configuration is valid")
    }

    /// Create a dispatcher with explicit bounds.
    pub fn with_config(
        config: SyscallConfig,
        audit: Arc<AuditLog>,
    ) -> Result<Self, SyscallConfigError> {
        config.validate()?;
        Ok(Self {
            config,
            state: Mutex::new(DispatcherState::default()),
            audit,
            total: AtomicU64::new(0),
            failures: AtomicU64::new(0),
            handler_panics: AtomicU64::new(0),
            latency_ns: AtomicU64::new(0),
        })
    }

    /// Return the explicit dispatcher bounds.
    pub const fn config(&self) -> SyscallConfig {
        self.config
    }

    /// Register or replace one host-owned handler.
    ///
    /// Replacement is explicit in the returned outcome and preserves the
    /// operation's deterministic name ordering. The dispatcher does not infer
    /// authorization; the adapter wiring point remains responsible for
    /// capability and configuration policy.
    pub fn register<F>(
        &self,
        name: impl Into<String>,
        handler: F,
    ) -> Result<RegistrationOutcome, SyscallRegistrationError>
    where
        F: Fn(&SyscallRequest) -> Result<JsonObject, SyscallFailure> + Send + Sync + 'static,
    {
        let name = name.into();
        self.validate_name(&name)?;
        let mut state = self.lock_state();
        let replacing = state.handlers.contains_key(&name);
        if !replacing && state.handlers.len() >= self.config.max_operations {
            return Err(SyscallRegistrationError::Full);
        }
        state.handlers.insert(name, Arc::new(handler));
        Ok(if replacing {
            RegistrationOutcome::Replaced
        } else {
            RegistrationOutcome::Inserted
        })
    }

    /// Remove one handler, returning whether it existed.
    pub fn unregister(&self, name: &str) -> bool {
        self.lock_state().handlers.remove(name).is_some()
    }

    /// Return registered operation names in deterministic order.
    pub fn registered_operations(&self) -> Vec<String> {
        self.lock_state().handlers.keys().cloned().collect()
    }

    /// Return the bounded audit trail used by this dispatcher.
    pub fn audit(&self) -> Arc<AuditLog> {
        Arc::clone(&self.audit)
    }

    /// Dispatch one request without allowing handler or registry panics out.
    pub fn dispatch(&self, request: SyscallRequest) -> SyscallResponse {
        let started = Instant::now();
        self.total.fetch_add(1, Ordering::Relaxed);

        let agent_id = if request.agent_id.trim().is_empty() {
            "unknown".to_owned()
        } else {
            request.agent_id.clone()
        };
        let op = request.op.clone();
        let mut panicked = false;
        let response = match request.validate(self.config) {
            Err(failure) => SyscallResponse::failure(failure),
            Ok(()) => {
                let handler = self.lock_state().handlers.get(&request.op).cloned();
                match handler {
                    None => SyscallResponse::failure(SyscallFailure::new(
                        "EINVAL",
                        format!("unknown syscall '{}'", request.op),
                    )),
                    Some(handler) => match catch_unwind(AssertUnwindSafe(|| handler(&request))) {
                        Ok(Ok(data)) => SyscallResponse::success(data),
                        Ok(Err(failure)) => SyscallResponse::failure(failure),
                        Err(_) => {
                            panicked = true;
                            SyscallResponse::failure(SyscallFailure::new(
                                "EFAULT",
                                "syscall handler panicked",
                            ))
                        }
                    },
                }
            }
        };

        if panicked {
            self.handler_panics.fetch_add(1, Ordering::Relaxed);
        }
        if !response.success {
            self.failures.fetch_add(1, Ordering::Relaxed);
        }
        self.latency_ns.fetch_add(
            started.elapsed().as_nanos().min(u64::MAX as u128) as u64,
            Ordering::Relaxed,
        );
        self.audit.record_fields(
            op,
            agent_id,
            response.success,
            response.error.clone(),
            if response.error_code.is_empty() {
                "dispatch".to_owned()
            } else {
                response.error_code.clone()
            },
        );
        response
    }

    /// Return cumulative dispatch and audit metrics.
    pub fn stats(&self) -> SyscallStats {
        let total = self.total.load(Ordering::Relaxed);
        let audit_entries = self.audit.stats().0;
        SyscallStats {
            total,
            failures: self.failures.load(Ordering::Relaxed),
            handler_panics: self.handler_panics.load(Ordering::Relaxed),
            registered_operations: self.lock_state().handlers.len(),
            audit_entries,
            average_latency_us: if total == 0 {
                0.0
            } else {
                self.latency_ns.load(Ordering::Relaxed) as f64 / total as f64 / 1_000.0
            },
        }
    }

    /// Flush a journal attached to the shared audit log.
    pub fn flush_audit(&self) -> std::io::Result<()> {
        self.audit.flush()
    }

    fn validate_name(&self, name: &str) -> Result<(), SyscallRegistrationError> {
        if name.trim().is_empty()
            || name.contains('\0')
            || name.len() > self.config.max_operation_bytes
        {
            return Err(SyscallRegistrationError::InvalidName);
        }
        Ok(())
    }

    fn lock_state(&self) -> MutexGuard<'_, DispatcherState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for SyscallDispatcher {
    /// Create an unwired dispatcher with an isolated audit log.
    fn default() -> Self {
        Self::new(Arc::new(AuditLog::new()))
    }
}

fn validate_text(
    value: &str,
    label: &str,
    max_bytes: usize,
    allow_empty: bool,
) -> Result<(), SyscallFailure> {
    if (!allow_empty && value.trim().is_empty()) || value.contains('\0') || value.len() > max_bytes
    {
        return Err(SyscallFailure::invalid(format!("invalid {label}")));
    }
    Ok(())
}

fn validate_json_object(object: &JsonObject) -> Result<(), SyscallFailure> {
    for (key, value) in object {
        if key.trim().is_empty() || key.contains('\0') {
            return Err(SyscallFailure::invalid("invalid argument key"));
        }
        validate_json_value(value)?;
    }
    Ok(())
}

fn validate_json_value(value: &JsonValue) -> Result<(), SyscallFailure> {
    match value {
        JsonValue::Null | JsonValue::Bool(_) | JsonValue::Number(_) => Ok(()),
        JsonValue::String(value) => {
            if value.contains('\0') {
                Err(SyscallFailure::invalid("invalid argument string"))
            } else {
                Ok(())
            }
        }
        JsonValue::Array(values) => values.iter().try_for_each(validate_json_value),
        JsonValue::Object(values) => validate_json_object(values),
    }
}
