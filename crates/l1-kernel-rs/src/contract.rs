//! Language-neutral value contracts mirrored from the Python3 L1 ports.

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
    /// Return the stable wire spelling used by Python3 snapshots.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Ready => "READY",
            Self::Running => "RUNNING",
            Self::Blocked => "BLOCKED",
            Self::Zombie => "ZOMBIE",
            Self::Stopped => "STOPPED",
        }
    }

    /// Parse a Python3 process-state snapshot without accepting unknown values.
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
    pub returncode: i32,
    /// Captured standard output as UTF-8 text.
    pub stdout: String,
    /// Captured standard error as UTF-8 text.
    pub stderr: String,
    /// Whether the adapter stopped the child because its deadline elapsed.
    pub timed_out: bool,
    /// Structured adapter error; empty when the child actually started.
    pub error_kind: String,
}

impl Default for ProcessResult {
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
    /// Return whether the process completed successfully under Python3 semantics.
    pub fn ok(&self) -> bool {
        self.returncode == 0 && !self.timed_out && self.error_kind.is_empty()
    }
}

/// Explicit, FFI-safe options for bounded process execution.
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ProcessOptions {
    /// Optional working directory.
    pub cwd: Option<String>,
    /// Optional UTF-8 input sent to the child.
    pub input_text: Option<String>,
    /// Optional environment replacement with deterministic key ordering.
    pub env: Option<BTreeMap<String, String>>,
    /// Optional executable used by shell execution.
    pub executable: Option<String>,
}

/// Dynamic signal record mirrored from the Python3 EventBus.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Signal {
    /// Stable built-in or registered event name.
    #[serde(rename = "type")]
    pub signal_type: String,
    /// JSON-compatible signal payload.
    pub data: JsonObject,
    /// Sending principal.
    pub sender: String,
    /// Optional target principal.
    pub target: String,
    /// Wall-clock timestamp supplied by the producer.
    pub timestamp: f64,
}

/// Primitive event value used by the kernel EventBusPort.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Event {
    /// Event name.
    #[serde(rename = "type")]
    pub event_type: String,
    /// Producing component.
    pub source: String,
    /// Severity string kept policy-neutral.
    pub severity: String,
    /// Human-readable message, if one exists.
    pub message: String,
    /// Locale tag for the message.
    pub message_locale: String,
    /// JSON-compatible event data.
    pub data: JsonObject,
}

/// Cumulative EventBus dispatch counters mirrored from `EventBus.stats()`.
#[derive(Debug, Clone, Copy, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct EventBusStats {
    /// Number of registered signal types with listeners.
    pub signal_types: usize,
    /// Number of typed listeners.
    pub listeners: usize,
    /// Number of retained history records.
    pub history: usize,
    /// Number of wildcard listeners.
    pub wildcard_listeners: usize,
    /// Maximum number of in-flight callback tasks.
    pub queue_max: usize,
    /// Current number of in-flight callback tasks.
    pub queue_depth: usize,
    /// Successfully submitted callback tasks.
    pub submitted: u64,
    /// Submitted callback tasks that completed.
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

#[cfg(test)]
mod tests {
    use super::{
        CapabilityResult, Event, EventBusStats, PROCESS_ERROR_EXECUTION,
        PROCESS_RETURN_EXECUTION_ERROR, ProcessOptions, ProcessResult, ProcessState, Signal,
    };
    use crate::sync::RwLock;
    use std::time::Duration;

    #[derive(serde::Deserialize)]
    struct ContractVector {
        case: String,
        kind: String,
        value: serde_json::Value,
    }

    #[test]
    fn process_result_matches_python_success_semantics() {
        assert!(ProcessResult::default().ok());
        assert!(
            !ProcessResult {
                returncode: PROCESS_RETURN_EXECUTION_ERROR,
                error_kind: PROCESS_ERROR_EXECUTION.to_owned(),
                ..ProcessResult::default()
            }
            .ok()
        );
    }

    #[test]
    fn process_state_wire_names_are_closed() {
        assert_eq!(ProcessState::Running.as_str(), "RUNNING");
        assert_eq!(ProcessState::parse("ZOMBIE"), Some(ProcessState::Zombie));
        assert_eq!(ProcessState::parse("UNKNOWN"), None);
    }

    #[test]
    fn event_stats_make_overload_explicit() {
        let clean = EventBusStats {
            submitted: 4,
            completed: 4,
            queue_depth: 0,
            ..EventBusStats::default()
        };
        assert!(clean.clean());
        assert_eq!(clean.drop_rate(), 0.0);

        let lossy = EventBusStats {
            submitted: 4,
            completed: 4,
            dropped: 1,
            ..clean
        };
        assert!(!lossy.clean());
        assert_eq!(lossy.dispatch_attempts(), 5);
        assert_eq!(lossy.drop_rate(), 0.2);
    }

    #[test]
    fn unwired_capability_is_fail_closed() {
        let result = CapabilityResult::unwired("read_file");
        assert!(!result.success);
        assert_eq!(result.capability, "read_file");
        assert!(result.error.contains("fail-closed"));
    }

    #[test]
    fn shared_vectors_round_trip_into_rust_contract_types() {
        let vectors: Vec<ContractVector> = serde_json::from_str(include_str!(
            "../../../tests/fixtures/kernel_value_vectors.json"
        ))
        .expect("kernel value fixture must be valid JSON");

        for vector in vectors {
            match vector.kind.as_str() {
                "process_result" => {
                    let raw = vector.value;
                    let result: ProcessResult = serde_json::from_value(raw.clone()).unwrap();
                    assert_eq!(result.ok(), vector.case == "process_success");
                    assert_eq!(serde_json::to_value(result).unwrap(), raw);
                }
                "process_options" => {
                    let raw = vector.value;
                    let options: ProcessOptions = serde_json::from_value(raw.clone()).unwrap();
                    assert_eq!(options.cwd.as_deref(), Some("/tmp"));
                    assert_eq!(options.executable.as_deref(), Some("/bin/sh"));
                    assert_eq!(serde_json::to_value(options).unwrap(), raw);
                }
                "process_states" => {
                    let raw = vector.value;
                    let states: Vec<ProcessState> = serde_json::from_value(raw.clone()).unwrap();
                    assert_eq!(states.len(), 5);
                    assert_eq!(serde_json::to_value(states).unwrap(), raw);
                }
                "signal" => {
                    let raw = vector.value;
                    let signal: Signal = serde_json::from_value(raw.clone()).unwrap();
                    assert_eq!(signal.signal_type, "TASK_DONE");
                    assert_eq!(serde_json::to_value(signal).unwrap(), raw);
                }
                "event" => {
                    let raw = vector.value;
                    let event: Event = serde_json::from_value(raw.clone()).unwrap();
                    assert_eq!(event.event_type, "tool.completed");
                    assert_eq!(serde_json::to_value(event).unwrap(), raw);
                }
                "event_bus_stats" => {
                    let raw = vector.value;
                    let stats: EventBusStats = serde_json::from_value(raw.clone()).unwrap();
                    assert_eq!(stats.clean(), vector.case == "event_bus_clean");
                    assert_eq!(serde_json::to_value(stats).unwrap(), raw);
                }
                "capability_result" => {
                    let raw = vector.value;
                    let result: CapabilityResult = serde_json::from_value(raw.clone()).unwrap();
                    assert!(!result.success);
                    assert!(result.error.contains("fail-closed"));
                    assert_eq!(serde_json::to_value(result).unwrap(), raw);
                }
                "rwlock" => {
                    let raw = vector.value;
                    let name = raw["name"].as_str().unwrap();
                    let agent_id = raw["agent_id"].as_str().unwrap();
                    let lock =
                        RwLock::new(name, Duration::from_millis(20), Duration::from_millis(1));
                    if vector.case == "rwlock_write_reentrant" {
                        assert_eq!(
                            serde_json::to_value(lock.write_lock(agent_id)).unwrap(),
                            raw["first"]
                        );
                        assert_eq!(
                            serde_json::to_value(lock.write_lock(agent_id)).unwrap(),
                            raw["second"]
                        );
                        assert_eq!(
                            serde_json::to_value(lock.unlock(agent_id)).unwrap(),
                            raw["release_once"]
                        );
                        assert_eq!(
                            serde_json::to_value(lock.unlock(agent_id)).unwrap(),
                            raw["release_twice"]
                        );
                    } else {
                        assert_eq!(
                            serde_json::to_value(lock.read_lock(agent_id)).unwrap(),
                            raw["read"]
                        );
                        assert_eq!(
                            serde_json::to_value(lock.write_lock(agent_id)).unwrap(),
                            raw["write"]
                        );
                        assert_eq!(
                            serde_json::to_value(lock.unlock(agent_id)).unwrap(),
                            raw["unlock"]
                        );
                    }
                    assert_eq!(serde_json::to_value(lock.status()).unwrap(), raw["status"]);
                }
                other => panic!("unknown contract vector kind: {other}"),
            }
        }
    }
}
