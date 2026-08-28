//! Fail-closed Agent process constraints for the Rust L1 admission boundary.
//!
//! This module evaluates declarative process intent before a host adapter
//! starts a child. It does not inspect the filesystem, mutate environment
//! variables, signal processes, or choose a terminal. All limits and allow
//! lists are injected by the caller, so an upper-layer Agent cannot obtain
//! implicit terminal or resource authority from a kernel default.

use std::collections::{BTreeSet, HashSet};

use serde::{Deserialize, Serialize};

use crate::terminal_probe::{TerminalKind, TerminalObservation};

/// Version of the Agent process constraint contract.
pub const PROCESS_CONSTRAINTS_CONTRACT_VERSION: u32 = 1;

/// Whether the requested argv is direct execution or shell-mediated.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentProcessMode {
    /// Execute the argv without shell interpretation.
    Direct,
    /// Execute argv using a discovered terminal invocation prefix.
    Shell,
}

/// Resource ceilings requested by one Agent process.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentResourceRequest {
    /// Maximum retained bytes per output stream.
    /// Hard cap on captured output bytes.
    /// Ceiling on requested output capture.
    pub max_output_bytes: usize,
    /// Optional CPU-time ceiling in milliseconds.
    /// Optional CPU-time budget in milliseconds.
    /// Ceiling on requested CPU budget; None = unlimited.
    pub max_cpu_time_ms: Option<u64>,
    /// Optional memory ceiling in bytes.
    /// Optional peak-memory budget in bytes.
    /// Ceiling on requested memory; None = unlimited.
    pub max_memory_bytes: Option<u64>,
}

/// Declarative process intent from an upper-layer Agent.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentProcessSpec {
    /// Stable process identity supplied by the owning AgentLoop.
    /// Caller-assigned process identity.
    pub process_id: String,
    /// Owning Agent identity.
    /// Requesting agent execution body.
    pub agent_id: String,
    /// Owning Cell identity.
    /// Owning cell domain.
    pub cell_id: String,
    /// Security ring supplied by the upper-layer identity binding.
    /// Authority ring of the requester.
    pub ring: u8,
    /// Execution mode.
    /// Direct-args vs shell classification.
    pub mode: AgentProcessMode,
    /// Full argv including executable at index zero.
    /// Argument vector (argv[0] is the executable).
    pub argv: Vec<String>,
    /// Optional working directory selected by the adapter.
    /// Working directory; None inherits the host default.
    pub cwd: Option<String>,
    /// Environment keys requested by the process.
    /// Environment keys forwarded to the child.
    pub environment_keys: Vec<String>,
    /// Whether the request replaces the inherited environment.
    /// Whether the child env is replaced rather than extended.
    pub replaces_environment: bool,
    /// Process-group identity, if the caller has one.
    /// Explicit process-group binding, if required.
    pub process_group_id: Option<String>,
    /// Caller-requested deadline in milliseconds.
    /// Wall-clock kill deadline in milliseconds.
    pub timeout_ms: u64,
    /// Caller-requested resource ceilings.
    /// Resource budget request evaluated by the allocator side.
    pub resources: AgentResourceRequest,
}

impl AgentProcessSpec {
    /// Return the executable at argv index zero, if present.
    pub fn executable(&self) -> Option<&str> {
        self.argv.first().map(String::as_str)
    }

    /// Validate fields that are independent of policy.
    ///
    /// # Errors
    ///
    /// InvalidSpec enumerating each violated launch-spec constraint
    /// (argv/executable shape, non-positive budgets, timeout ceilings).
    ///
    /// # Errors
    ///
    /// InvalidPolicy enumerating each self-contradiction (e.g. shell
    /// launches disabled while shell mode required, interactive/PTY/group
    /// requirements conflicting with allowlists).
    ///
    /// # Errors
    ///
    /// InvalidSpec enumerating violated launch-spec constraints.
    pub fn validate(&self) -> Result<(), ProcessConstraintError> {
        if self.process_id.trim().is_empty()
            || self.agent_id.trim().is_empty()
            || self.cell_id.trim().is_empty()
        {
            return Err(ProcessConstraintError::InvalidSpec(
                "process_id, agent_id, and cell_id are required".to_owned(),
            ));
        }
        if self.argv.is_empty() || self.argv.iter().any(|value| value.is_empty()) {
            return Err(ProcessConstraintError::InvalidSpec(
                "argv must contain a non-empty executable and arguments".to_owned(),
            ));
        }
        if self.cwd.as_deref().is_some_and(str::is_empty) {
            return Err(ProcessConstraintError::InvalidSpec(
                "cwd cannot be empty when supplied".to_owned(),
            ));
        }
        if self
            .environment_keys
            .iter()
            .any(|key| key.trim().is_empty())
        {
            return Err(ProcessConstraintError::InvalidSpec(
                "environment keys cannot be empty".to_owned(),
            ));
        }
        if self.environment_keys.iter().collect::<HashSet<_>>().len() != self.environment_keys.len()
        {
            return Err(ProcessConstraintError::InvalidSpec(
                "environment keys must be unique".to_owned(),
            ));
        }
        if self.resources.max_output_bytes == 0 {
            return Err(ProcessConstraintError::InvalidSpec(
                "max_output_bytes must be greater than zero".to_owned(),
            ));
        }
        if self
            .resources
            .max_cpu_time_ms
            .is_some_and(|value| value == 0)
            || self
                .resources
                .max_memory_bytes
                .is_some_and(|value| value == 0)
        {
            return Err(ProcessConstraintError::InvalidSpec(
                "optional resource ceilings must be greater than zero".to_owned(),
            ));
        }
        Ok(())
    }
}

/// Explicit ceilings and allow-lists applied at process admission.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentProcessPolicy {
    /// Rings allowed to request a child process.
    /// Rings permitted to launch under this policy.
    pub allowed_rings: BTreeSet<u8>,
    /// Optional terminal identity allow-list.
    /// Terminal allowlist; None means unrestricted.
    pub allowed_terminal_ids: Option<BTreeSet<String>>,
    /// Optional terminal-family allow-list.
    /// Terminal-kind allowlist; None means unrestricted.
    pub allowed_terminal_kinds: Option<BTreeSet<TerminalKind>>,
    /// Optional executable allow-list.
    /// Executable basename allowlist; None means unrestricted.
    pub allowed_executables: Option<BTreeSet<String>>,
    /// Optional lexical working-directory prefixes.
    /// Working-directory prefix allowlist (territory scoping).
    pub allowed_cwd_prefixes: Option<Vec<String>>,
    /// Environment keys permitted in a request.
    /// Environment keys that may be forwarded.
    pub allowed_environment_keys: BTreeSet<String>,
    /// Environment keys always rejected, even if allowed above.
    /// Environment keys always stripped (deny overrides allow).
    pub denied_environment_keys: BTreeSet<String>,
    /// Whether environment replacement is permitted.
    /// Whether full environment replacement is permitted.
    pub allow_environment_replacement: bool,
    /// Maximum argv entries including executable.
    /// Maximum number of argv items accepted.
    pub max_argv_items: usize,
    /// Maximum requested timeout.
    /// Ceiling any requested timeout may not exceed.
    pub max_timeout_ms: u64,
    /// Maximum output retained per stream.
    pub max_output_bytes: usize,
    /// Optional CPU ceiling.
    pub max_cpu_time_ms: Option<u64>,
    /// Optional memory ceiling.
    pub max_memory_bytes: Option<u64>,
    /// Whether shell-mediated execution is permitted.
    /// Whether shell-mode launches are allowed at all.
    pub allow_shell: bool,
    /// Whether shell requests must have an interactive terminal.
    /// Whether an attached interactive terminal is mandatory.
    pub require_interactive_terminal: bool,
    /// Whether shell requests must have PTY support.
    /// Whether a PTY-backed terminal is mandatory.
    pub require_pty: bool,
    /// Whether every admitted process must belong to a group.
    /// Whether explicit process-group binding is mandatory.
    pub require_process_group: bool,
}

impl AgentProcessPolicy {
    /// Validate policy bounds before it is installed by a host adapter.
    ///
    /// # Errors
    ///
    /// InvalidPolicy when allowed_rings is empty, argv/timeout/output
    /// caps are zero, or requirement flags contradict allowlists.
    pub fn validate(&self) -> Result<(), ProcessConstraintError> {
        if self.allowed_rings.is_empty()
            || self.max_argv_items == 0
            || self.max_timeout_ms == 0
            || self.max_output_bytes == 0
        {
            return Err(ProcessConstraintError::InvalidPolicy(
                "rings, argv, timeout, and output limits must be non-zero".to_owned(),
            ));
        }
        if self
            .allowed_cwd_prefixes
            .as_ref()
            .is_some_and(|prefixes| prefixes.iter().any(|prefix| prefix.is_empty()))
        {
            return Err(ProcessConstraintError::InvalidPolicy(
                "cwd prefixes cannot be empty".to_owned(),
            ));
        }
        if self.max_cpu_time_ms.is_some_and(|value| value == 0)
            || self.max_memory_bytes.is_some_and(|value| value == 0)
        {
            return Err(ProcessConstraintError::InvalidPolicy(
                "optional policy resource ceilings must be greater than zero".to_owned(),
            ));
        }
        Ok(())
    }
}

/// Structured reason for rejecting a process request.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessConstraintViolation {
    /// Ring is not in the policy allow-list.
    RingNotAllowed { ring: u8 },
    /// Shell execution is disabled.
    ShellNotAllowed,
    /// The request requires a discovered terminal.
    TerminalRequired,
    /// No terminal was supplied for the request.
    TerminalMissing,
    /// The supplied terminal cannot start.
    TerminalUnavailable,
    /// Terminal identity is outside the allow-list.
    TerminalIdNotAllowed { terminal_id: String },
    /// Terminal family is outside the allow-list.
    TerminalKindNotAllowed { kind: TerminalKind },
    /// Shell argv does not match the discovered invocation prefix.
    TerminalInvocationMismatch,
    /// Shell argv contains no command after the invocation prefix.
    TerminalCommandMissing,
    /// The terminal lacks required interactive support.
    InteractiveTerminalRequired,
    /// The terminal lacks required PTY support.
    PtyRequired,
    /// Executable is outside the allow-list.
    ExecutableNotAllowed { executable: String },
    /// argv exceeds the configured item bound.
    ArgvLimitExceeded { actual: usize, limit: usize },
    /// Working directory is required by policy.
    WorkingDirectoryRequired,
    /// Working directory is outside policy prefixes.
    WorkingDirectoryNotAllowed { cwd: String },
    /// Environment replacement is disabled.
    EnvironmentReplacementNotAllowed,
    /// Environment key is outside the allow-list.
    EnvironmentKeyNotAllowed { key: String },
    /// Environment key is explicitly denied.
    EnvironmentKeyDenied { key: String },
    /// Timeout exceeds the policy ceiling.
    TimeoutExceeded { actual: u64, limit: u64 },
    /// Output retention exceeds the policy ceiling.
    OutputLimitExceeded { actual: usize, limit: usize },
    /// CPU request exceeds the policy ceiling.
    CpuLimitExceeded { actual: u64, limit: u64 },
    /// Memory request exceeds the policy ceiling.
    MemoryLimitExceeded { actual: u64, limit: u64 },
    /// Process-group membership is required.
    ProcessGroupRequired,
    /// Adapter executable override differs from the admitted argv.
    AdapterExecutableMismatch {
        expected: String,
        actual: Option<String>,
    },
    /// Adapter working-directory option differs from the admitted request.
    AdapterWorkingDirectoryMismatch {
        expected: Option<String>,
        actual: Option<String>,
    },
    /// Adapter environment keys differ from the admitted request.
    AdapterEnvironmentMismatch {
        expected: Vec<String>,
        actual: Vec<String>,
    },
}

/// Fail-closed errors from process policy construction or evaluation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessConstraintError {
    /// A request field violates the value contract.
    InvalidSpec(String),
    /// A policy field violates the value contract.
    InvalidPolicy(String),
    /// One or more hard constraints rejected the request.
    Violations(Vec<ProcessConstraintViolation>),
}

/// Successful process admission receipt consumed by a host adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessAdmission {
    /// Contract version for the receipt.
    pub contract_version: u32,
    /// Stable process identity.
    pub process_id: String,
    /// Validated argv to pass to a direct process adapter.
    pub argv: Vec<String>,
    /// Selected terminal identity for shell requests.
    pub terminal_id: Option<String>,
}

/// Pure policy evaluator; it performs no OS calls or process mutation.
#[derive(Debug, Clone)]
pub struct ProcessConstraintEvaluator {
    policy: AgentProcessPolicy,
}

impl ProcessConstraintEvaluator {
    /// Construct an evaluator from a validated explicit policy.
    ///
    /// # Errors
    ///
    /// InvalidPolicy when policy floors/caps are inconsistent.
    pub fn new(policy: AgentProcessPolicy) -> Result<Self, ProcessConstraintError> {
        policy.validate()?;
        Ok(Self { policy })
    }

    /// Return the immutable policy used for admissions.
    pub const fn policy(&self) -> &AgentProcessPolicy {
        &self.policy
    }

    /// Admit one process request after evaluating every hard constraint.
    pub fn admit(
        &self,
        spec: &AgentProcessSpec,
        terminal: Option<&TerminalObservation>,
    ) -> Result<ProcessAdmission, ProcessConstraintError> {
        spec.validate()?;
        let mut violations = Vec::new();
        if !self.policy.allowed_rings.contains(&spec.ring) {
            violations.push(ProcessConstraintViolation::RingNotAllowed { ring: spec.ring });
        }
        if spec.mode == AgentProcessMode::Shell && !self.policy.allow_shell {
            violations.push(ProcessConstraintViolation::ShellNotAllowed);
        }
        if spec.argv.len() > self.policy.max_argv_items {
            violations.push(ProcessConstraintViolation::ArgvLimitExceeded {
                actual: spec.argv.len(),
                limit: self.policy.max_argv_items,
            });
        }
        let executable = spec.executable().unwrap_or_default();
        if self
            .policy
            .allowed_executables
            .as_ref()
            .is_some_and(|allowed| !allowed.contains(executable))
        {
            violations.push(ProcessConstraintViolation::ExecutableNotAllowed {
                executable: executable.to_owned(),
            });
        }
        self.check_terminal(spec, executable, terminal, &mut violations);
        self.check_cwd(spec, &mut violations);
        self.check_environment(spec, &mut violations);
        if spec.timeout_ms > self.policy.max_timeout_ms {
            violations.push(ProcessConstraintViolation::TimeoutExceeded {
                actual: spec.timeout_ms,
                limit: self.policy.max_timeout_ms,
            });
        }
        if spec.resources.max_output_bytes > self.policy.max_output_bytes {
            violations.push(ProcessConstraintViolation::OutputLimitExceeded {
                actual: spec.resources.max_output_bytes,
                limit: self.policy.max_output_bytes,
            });
        }
        if let (Some(actual), Some(limit)) =
            (spec.resources.max_cpu_time_ms, self.policy.max_cpu_time_ms)
            && actual > limit
        {
            violations.push(ProcessConstraintViolation::CpuLimitExceeded { actual, limit });
        }
        if let (Some(actual), Some(limit)) = (
            spec.resources.max_memory_bytes,
            self.policy.max_memory_bytes,
        ) && actual > limit
        {
            violations.push(ProcessConstraintViolation::MemoryLimitExceeded { actual, limit });
        }
        if self.policy.require_process_group && spec.process_group_id.is_none() {
            violations.push(ProcessConstraintViolation::ProcessGroupRequired);
        }
        if !violations.is_empty() {
            return Err(ProcessConstraintError::Violations(violations));
        }
        Ok(ProcessAdmission {
            contract_version: PROCESS_CONSTRAINTS_CONTRACT_VERSION,
            process_id: spec.process_id.clone(),
            argv: spec.argv.clone(),
            terminal_id: (spec.mode == AgentProcessMode::Shell)
                .then(|| terminal.map(|value| value.terminal_id.clone()))
                .flatten(),
        })
    }

    /// Validate terminal constraints for one process spec.
    fn check_terminal(
        &self,
        spec: &AgentProcessSpec,
        executable: &str,
        terminal: Option<&TerminalObservation>,
        violations: &mut Vec<ProcessConstraintViolation>,
    ) {
        if spec.mode == AgentProcessMode::Direct {
            return;
        }
        let Some(terminal) = terminal else {
            if self.policy.require_interactive_terminal || self.policy.require_pty {
                violations.push(ProcessConstraintViolation::TerminalRequired);
            } else {
                violations.push(ProcessConstraintViolation::TerminalMissing);
            }
            return;
        };
        if !terminal.available {
            violations.push(ProcessConstraintViolation::TerminalUnavailable);
        }
        if self
            .policy
            .allowed_terminal_ids
            .as_ref()
            .is_some_and(|allowed| !allowed.contains(&terminal.terminal_id))
        {
            violations.push(ProcessConstraintViolation::TerminalIdNotAllowed {
                terminal_id: terminal.terminal_id.clone(),
            });
        }
        if self
            .policy
            .allowed_terminal_kinds
            .as_ref()
            .is_some_and(|allowed| !allowed.contains(&terminal.kind))
        {
            violations.push(ProcessConstraintViolation::TerminalKindNotAllowed {
                kind: terminal.kind.clone(),
            });
        }
        if self.policy.require_interactive_terminal && !terminal.interactive {
            violations.push(ProcessConstraintViolation::InteractiveTerminalRequired);
        }
        if self.policy.require_pty && !terminal.pty {
            violations.push(ProcessConstraintViolation::PtyRequired);
        }
        let prefix = std::iter::once(&terminal.executable)
            .chain(terminal.invocation.iter())
            .map(String::as_str)
            .collect::<Vec<_>>();
        if spec.argv.len() <= prefix.len() {
            violations.push(ProcessConstraintViolation::TerminalCommandMissing);
        } else if !spec
            .argv
            .iter()
            .zip(prefix.iter())
            .all(|(actual, expected)| actual == expected)
            || executable != terminal.executable
        {
            violations.push(ProcessConstraintViolation::TerminalInvocationMismatch);
        }
    }

    /// Validate the cwd against allowed prefixes.
    fn check_cwd(&self, spec: &AgentProcessSpec, violations: &mut Vec<ProcessConstraintViolation>) {
        let Some(prefixes) = &self.policy.allowed_cwd_prefixes else {
            return;
        };
        let Some(cwd) = spec.cwd.as_deref() else {
            violations.push(ProcessConstraintViolation::WorkingDirectoryRequired);
            return;
        };
        if has_parent_or_current_component(cwd)
            || !prefixes
                .iter()
                .any(|prefix| path_within_prefix(cwd, prefix))
        {
            violations.push(ProcessConstraintViolation::WorkingDirectoryNotAllowed {
                cwd: cwd.to_owned(),
            });
        }
    }

    /// Validate environment variables against policy.
    fn check_environment(
        &self,
        spec: &AgentProcessSpec,
        violations: &mut Vec<ProcessConstraintViolation>,
    ) {
        if spec.replaces_environment && !self.policy.allow_environment_replacement {
            violations.push(ProcessConstraintViolation::EnvironmentReplacementNotAllowed);
        }
        for key in &spec.environment_keys {
            if self.policy.denied_environment_keys.contains(key) {
                violations
                    .push(ProcessConstraintViolation::EnvironmentKeyDenied { key: key.clone() });
            } else if !self.policy.allowed_environment_keys.contains(key) {
                violations.push(ProcessConstraintViolation::EnvironmentKeyNotAllowed {
                    key: key.clone(),
                });
            }
        }
    }
}

/// Return whether a path is within a prefix using boundary rules.
fn path_within_prefix(path: &str, prefix: &str) -> bool {
    let path = path.trim_end_matches(['/', '\\']);
    let prefix = prefix.trim_end_matches(['/', '\\']);
    path == prefix
        || path
            .strip_prefix(prefix)
            .is_some_and(|rest| rest.starts_with('/') || rest.starts_with('\\'))
}

/// Detect `..` or `.` components in a path.
fn has_parent_or_current_component(path: &str) -> bool {
    path.split(['/', '\\'])
        .any(|component| component == "." || component == "..")
}
