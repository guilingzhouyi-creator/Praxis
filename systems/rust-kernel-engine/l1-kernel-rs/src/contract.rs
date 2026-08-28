//! Language-neutral value contracts mirrored from the Python L1 ports.

use std::collections::BTreeMap;

/// Return code used when a bounded process execution times out.
pub const PROCESS_RETURN_TIMEOUT: i32 = -1;
/// Return code used when the adapter cannot execute a process.
pub const PROCESS_RETURN_EXECUTION_ERROR: i32 = -2;
/// Empty error kind means the child process started successfully.
pub const PROCESS_ERROR_NONE: &str = "";
/// Error kind for an executable or shell that cannot be found.
pub const PROCESS_ERROR_NOT_FOUND: &str = "not_found";
/// Error kind for an adapter-side execution failure.
pub const PROCESS_ERROR_EXECUTION: &str = "execution";

/// JSON-compatible value used at language boundaries without interpreter objects.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(untagged)]
pub enum JsonValue {
    /// JSON null.
    Null,
    /// JSON boolean.
    Bool(bool),
    /// JSON number preserving integer versus fractional wire representation.
    Number(serde_json::Number),
    /// JSON string.
    String(String),
    /// JSON array.
    Array(Vec<JsonValue>),
    /// JSON object with deterministic key ordering.
    Object(BTreeMap<String, JsonValue>),
}

/// JSON object crossing a Port or capability boundary.
pub type JsonObject = BTreeMap<String, JsonValue>;

/// Process lifecycle state mirrored from `l1.kernel.process.ProcessState`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ProcessState {
    /// Registered and ready to run.
    Ready,
    /// Currently executing.
    Running,
    /// Temporarily blocked.
    Blocked,
    /// Terminated and awaiting reaping.
    Zombie,
    /// Stopped or cancelled.
    Stopped,
}

impl ProcessState {
    /// Return the stable wire spelling used by Python snapshots.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Ready => "READY",
            Self::Running => "RUNNING",
            Self::Blocked => "BLOCKED",
            Self::Zombie => "ZOMBIE",
            Self::Stopped => "STOPPED",
        }
    }

    /// Parse a Python process-state snapshot without accepting unknown values.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "READY" => Some(Self::Ready),
            "RUNNING" => Some(Self::Running),
            "BLOCKED" => Some(Self::Blocked),
            "ZOMBIE" => Some(Self::Zombie),
            "STOPPED" => Some(Self::Stopped),
            _ => None,
        }
    }
}

/// FFI-clean result returned by a bounded process adapter.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ProcessResult {
    /// Child exit code, or a synthetic adapter code for timeout/execution failure.
    /// Child exit code (negative conventions host-defined).
    pub returncode: i32,
    /// Captured standard output as UTF-8 text.
    /// Captured stdout (bounded by caller options).
    pub stdout: String,
    /// Captured standard error as UTF-8 text.
    /// Captured stderr (bounded by caller options).
    pub stderr: String,
    /// Whether the adapter stopped the child because its deadline elapsed.
    /// Whether the deadline killed the child.
    pub timed_out: bool,
    /// Structured adapter error; empty when the child actually started.
    /// Stable adapter-error classification; empty on success.
    pub error_kind: String,
}

impl Default for ProcessResult {
    /// Create a default process result.
    fn default() -> Self {
        Self {
            returncode: 0,
            stdout: String::new(),
            stderr: String::new(),
            timed_out: false,
            error_kind: PROCESS_ERROR_NONE.to_owned(),
        }
    }
}

impl ProcessResult {
    /// Return whether the process completed successfully under Python semantics.
    pub fn ok(&self) -> bool {
        self.returncode == 0 && !self.timed_out && self.error_kind.is_empty()
    }
}

/// Explicit, FFI-safe options for bounded process execution.
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ProcessOptions {
    /// Optional working directory.
    /// Working directory override.
    pub cwd: Option<String>,
    /// Optional UTF-8 input sent to the child.
    /// Stdin payload override.
    pub input_text: Option<String>,
    /// Optional environment replacement with deterministic key ordering.
    /// Environment overlay applied by the host.
    pub env: Option<BTreeMap<String, String>>,
    /// Optional executable used by shell execution.
    /// Explicit executable override.
    pub executable: Option<String>,
}

/// Dynamic signal record mirrored from the Python EventBus.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Signal {
    /// Stable built-in or registered event name.
    #[serde(rename = "type")]
    /// IRQ/signal classification.
    pub signal_type: String,
    /// JSON-compatible signal payload.
    /// Signal payload.
    /// Structured event attributes.
    pub data: JsonObject,
    /// Sending principal.
    /// Emitting component id.
    pub sender: String,
    /// Optional target principal.
    /// Addressed component or broadcast marker.
    pub target: String,
    /// Wall-clock timestamp supplied by the producer.
    /// Unix timestamp in seconds.
    pub timestamp: f64,
}

/// Primitive event value used by the kernel EventBusPort.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Event {
    /// Event name.
    #[serde(rename = "type")]
    /// Observability event classification.
    pub event_type: String,
    /// Producing component.
    /// Emitting subsystem label.
    pub source: String,
    /// Severity string kept policy-neutral.
    /// Severity tier (debug/info/warn/error).
    pub severity: String,
    /// Human-readable message, if one exists.
    /// Human-readable summary.
    pub message: String,
    /// Locale tag for the message.
    /// Locale tag of `message`.
    pub message_locale: String,
    /// JSON-compatible event data.
    pub data: JsonObject,
}

/// Cumulative EventBus dispatch counters mirrored from `EventBus.stats()`.
#[derive(Debug, Clone, Copy, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct EventBusStats {
    /// Number of registered signal types with listeners.
    /// Registered signal-type count.
    pub signal_types: usize,
    /// Number of typed listeners.
    /// Attached typed listeners.
    pub listeners: usize,
    /// Number of retained history records.
    /// Bounded history entries retained.
    pub history: usize,
    /// Number of wildcard listeners.
    /// Listeners subscribed to all signals.
    pub wildcard_listeners: usize,
    /// Maximum number of in-flight callback tasks.
    /// Dispatch queue capacity.
    pub queue_max: usize,
    /// Current number of in-flight callback tasks.
    /// Current dispatch queue depth.
    pub queue_depth: usize,
    /// Successfully submitted callback tasks.
    /// Lifetime submissions accepted.
    pub submitted: u64,
    /// Submitted callback tasks that completed.
    /// Lifetime dispatches completed.
    pub completed: u64,
    /// Callback tasks rejected by bounded overload or executor failure.
    pub dropped: u64,
}

impl EventBusStats {
    /// Return the total number of callback dispatch attempts.
    pub const fn dispatch_attempts(self) -> u64 {
        self.submitted + self.dropped
    }

    /// Return the cumulative drop rate, using zero for an empty denominator.
    pub fn drop_rate(self) -> f64 {
        let attempts = self.dispatch_attempts();
        if attempts == 0 {
            0.0
        } else {
            self.dropped as f64 / attempts as f64
        }
    }

    /// Return whether all submitted callbacks drained without a drop.
    pub const fn clean(self) -> bool {
        self.dropped == 0 && self.queue_depth == 0 && self.completed == self.submitted
    }
}

/// Capability request crossing the single execution authority.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CapabilityRequest {
    /// Calling process or interactive principal.
    pub agent_id: String,
    /// Registered capability name.
    pub name: String,
    /// JSON-compatible arguments.
    pub args: JsonObject,
    /// Optional policy domain supplied by the caller.
    pub domain: String,
    /// Optional card/tool nature supplied by the caller.
    pub nature: String,
    /// Whether the caller was authenticated as an interactive principal.
    pub interactive: bool,
}

/// Result returned by the single capability authority.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CapabilityResult {
    /// Whether the capability was accepted and executed.
    pub success: bool,
    /// Stable error text for denied or failed calls.
    pub error: String,
    /// Capability name retained for audit correlation.
    pub capability: String,
    /// Additional primitive result data.
    pub data: JsonObject,
}

impl CapabilityResult {
    /// Build the fail-closed result used when no executor is wired.
    pub fn unwired(name: impl Into<String>) -> Self {
        Self {
            success: false,
            error: "no execution authority (fail-closed)".to_owned(),
            capability: name.into(),
            data: JsonObject::new(),
        }
    }
}
