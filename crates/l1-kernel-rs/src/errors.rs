//! Provider-neutral structured errors and explicit trace propagation values.

use std::collections::BTreeMap;
use std::fmt;

use serde::{Deserialize, Serialize};

/// Maximum cause text retained in a structured error response.
pub const ERROR_CAUSE_MAXLEN: usize = 200;

/// Stable machine-readable error and response value.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct KernelError {
    /// Machine-readable error code, for example `E_TIMEOUT`.
    pub code: String,
    /// Human-readable message selected by the adapter or catalog.
    pub message: String,
    /// Bounded source-cause text.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub cause: String,
    /// Structured context supplied by the failing operation.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub context: BTreeMap<String, serde_json::Value>,
    /// Explicit request correlation id supplied by a TracePort adapter.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub trace_id: String,
}

impl KernelError {
    /// Construct an error using the built-in default-message catalog.
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        let code = code.into();
        let supplied = message.into();
        Self {
            message: if supplied.is_empty() {
                default_message(&code)
            } else {
                supplied
            },
            code,
            cause: String::new(),
            context: BTreeMap::new(),
            trace_id: String::new(),
        }
    }

    /// Construct an error using an injected catalog, without global state.
    pub fn from_catalog(
        catalog: &ErrorCatalog,
        code: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        let code = code.into();
        let supplied = message.into();
        let mut error = Self::new(code.clone(), supplied);
        if error.message == format!("Unknown error: {code}")
            && let Some(default) = catalog.get(&code)
        {
            error.message = default.to_owned();
        }
        error
    }

    /// Attach a bounded source cause.
    pub fn with_cause(mut self, cause: impl Into<String>) -> Self {
        self.cause = cause.into().chars().take(ERROR_CAUSE_MAXLEN).collect();
        self
    }

    /// Attach a JSON context value under one key.
    pub fn with_context(mut self, key: impl Into<String>, value: serde_json::Value) -> Self {
        self.context.insert(key.into(), value);
        self
    }

    /// Attach an explicit trace id from the adapter boundary.
    pub fn with_trace_id(mut self, trace_id: impl Into<String>) -> Self {
        self.trace_id = trace_id.into();
        self
    }

    /// Convert to the Python-compatible failure response shape.
    pub fn to_response(&self) -> ErrorResponse {
        ErrorResponse {
            success: false,
            error: self.message.clone(),
            error_code: self.code.clone(),
            context: (!self.context.is_empty()).then(|| self.context.clone()),
            cause: (!self.cause.is_empty()).then(|| self.cause.clone()),
        }
    }
}

impl fmt::Display for KernelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "[{}] {}", self.code, self.message)
    }
}

impl std::error::Error for KernelError {}

/// Serializable error response returned by kernel-facing adapters.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ErrorResponse {
    /// Always false for an error response.
    pub success: bool,
    /// Resolved human-readable message.
    pub error: String,
    /// Machine-readable error code.
    pub error_code: String,
    /// Optional operation context.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub context: Option<BTreeMap<String, serde_json::Value>>,
    /// Optional bounded source cause.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cause: Option<String>,
}

/// Explicit trace value that an adapter can carry across a kernel call.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TraceContext {
    /// Unified request correlation id; empty means no active trace.
    #[serde(default)]
    pub trace_id: String,
}

impl TraceContext {
    /// Create a context from an externally-owned trace id.
    pub fn new(trace_id: impl Into<String>) -> Self {
        Self {
            trace_id: trace_id.into(),
        }
    }

    /// Return whether this context carries a trace id.
    pub fn is_set(&self) -> bool {
        !self.trace_id.is_empty()
    }

    /// Propagate this trace id to an error value without generating a new id.
    pub fn propagate(&self, mut error: KernelError) -> KernelError {
        if error.trace_id.is_empty() {
            error.trace_id = self.trace_id.clone();
        }
        error
    }
}

/// Mutable error-code catalog owned by an adapter or test.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorCatalog {
    /// Error code to default English message.
    pub entries: BTreeMap<String, String>,
}

impl ErrorCatalog {
    /// Build the built-in catalog used by the Python kernel.
    pub fn builtin() -> Self {
        let mut catalog = Self {
            entries: BTreeMap::new(),
        };
        for (code, message) in [
            ("E_INTERNAL", "Internal error"),
            ("E_TIMEOUT", "Operation timed out"),
            ("E_INVALID_PARAMS", "Invalid parameters"),
            ("E_NOT_FOUND", "Resource not found"),
            ("E_CONSTITUTION_BLOCKED", "Blocked by constitution"),
            ("E_GATECHAIN_BLOCKED", "Blocked by gate chain"),
            ("E_TOOL_MUTED", "Tool is muted"),
            ("E_TOOL_NOT_FOUND", "Tool not found in registry"),
            ("E_RESOURCE_EXHAUSTED", "Resource exhausted"),
            ("E_PERMISSION_DENIED", "Permission denied"),
            ("E_CELL_EMERGENCY", "Cell is in emergency stop mode"),
            ("E_CHECKPOINT_RESTORE", "Failed to restore checkpoint"),
            ("E_AGENT_CRASHED", "Agent has crashed"),
            ("E_HUMAN_REJECTED", "Rejected by human approval"),
            ("E_APPROVAL_TIMEOUT", "Approval request timed out"),
            ("E_MCP_FAILED", "MCP call failed"),
            ("E_UNKNOWN_TOOL", "Unknown tool"),
            ("E_HANDLER_ERROR", "Tool handler error"),
            ("E_MEMORY_REJECTED", "Memory rejected by quality filter"),
            ("E_SANDBOX_ERROR", "Sandbox operation failed"),
        ] {
            catalog.register(code, message);
        }
        catalog
    }

    /// Register or replace one default message.
    pub fn register(&mut self, code: impl Into<String>, message: impl Into<String>) {
        self.entries.insert(code.into(), message.into());
    }

    /// Look up a default message without mutating the catalog.
    pub fn get(&self, code: &str) -> Option<&str> {
        self.entries.get(code).map(String::as_str)
    }
}

impl Default for ErrorCatalog {
    fn default() -> Self {
        Self::builtin()
    }
}

fn default_message(code: &str) -> String {
    ErrorCatalog::builtin()
        .get(code)
        .map(str::to_owned)
        .unwrap_or_else(|| format!("Unknown error: {code}"))
}
