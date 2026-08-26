//! Injected terminal capability discovery for the Rust L1 boundary.
//!
//! The kernel never scans `PATH`, reads host environment variables, or assumes
//! a shell path. A host adapter performs those observations and injects typed
//! records here; this module validates, filters, and deterministically selects
//! one record using caller-supplied policy.

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};

/// Version of the terminal capability/discovery contract.
pub const TERMINAL_PROBE_CONTRACT_VERSION: u32 = 1;

/// Stable terminal family used for policy matching.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalKind {
    /// Windows Command Prompt.
    Cmd,
    /// Windows PowerShell, including PowerShell 7.
    PowerShell,
    /// POSIX Bash.
    Bash,
    /// Git for Windows Bash.
    GitBash,
    /// Z shell.
    Zsh,
    /// Fish shell.
    Fish,
    /// Host-defined terminal family.
    Other(String),
}

impl TerminalKind {
    /// Return the stable policy spelling for this terminal family.
    pub fn as_str(&self) -> &str {
        match self {
            Self::Cmd => "cmd",
            Self::PowerShell => "power_shell",
            Self::Bash => "bash",
            Self::GitBash => "git_bash",
            Self::Zsh => "zsh",
            Self::Fish => "fish",
            Self::Other(value) => value.as_str(),
        }
    }
}

/// A host-observed terminal capability record.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalObservation {
    /// Stable adapter-assigned terminal identity.
    pub terminal_id: String,
    /// Terminal family used by policy, not by execution dispatch.
    pub kind: TerminalKind,
    /// Executable resolved by the host adapter.
    pub executable: String,
    /// Adapter-supplied argument prefix for shell execution.
    pub invocation: Vec<String>,
    /// Version reported by the host probe, if available.
    pub version: Option<String>,
    /// Whether the executable was found and can be started.
    pub available: bool,
    /// Whether the terminal supports an interactive session.
    pub interactive: bool,
    /// Whether the host adapter can attach a PTY to this terminal.
    pub pty: bool,
    /// Encoding reported by the host adapter.
    pub encoding: String,
    /// Probe implementation or host source identifier.
    pub source: String,
}

impl TerminalObservation {
    /// Construct an observation from host-supplied facts.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        terminal_id: impl Into<String>,
        kind: TerminalKind,
        executable: impl Into<String>,
        invocation: Vec<String>,
        version: Option<String>,
        available: bool,
        interactive: bool,
        pty: bool,
        encoding: impl Into<String>,
        source: impl Into<String>,
    ) -> Self {
        Self {
            terminal_id: terminal_id.into(),
            kind,
            executable: executable.into(),
            invocation,
            version,
            available,
            interactive,
            pty,
            encoding: encoding.into(),
            source: source.into(),
        }
    }

    /// Validate identity and host-provided execution metadata.
    pub fn validate(&self) -> Result<(), TerminalProbeError> {
        if self.terminal_id.trim().is_empty()
            || self.executable.trim().is_empty()
            || self.encoding.trim().is_empty()
            || self.source.trim().is_empty()
        {
            return Err(TerminalProbeError::InvalidObservation {
                terminal_id: self.terminal_id.clone(),
                reason: "identity, executable, encoding, and source are required".to_owned(),
            });
        }
        if self.invocation.iter().any(|arg| arg.is_empty()) {
            return Err(TerminalProbeError::InvalidObservation {
                terminal_id: self.terminal_id.clone(),
                reason: "invocation arguments cannot be empty".to_owned(),
            });
        }
        Ok(())
    }

    /// Build the exact shell argv described by this observation.
    pub fn command_argv(&self, command: impl Into<String>) -> Vec<String> {
        let mut argv = Vec::with_capacity(self.invocation.len() + 2);
        argv.push(self.executable.clone());
        argv.extend(self.invocation.iter().cloned());
        argv.push(command.into());
        argv
    }
}

/// Explicit policy for filtering host observations.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalProbeConfig {
    /// Whether unavailable observations are rejected from the eligible set.
    pub require_available: bool,
    /// Whether an eligible terminal must support interactive operation.
    pub require_interactive: bool,
    /// Whether an eligible terminal must support PTY attachment.
    pub require_pty: bool,
    /// Optional allow-list of terminal families.
    pub allowed_kinds: Option<BTreeSet<TerminalKind>>,
    /// Explicit preference order; no built-in terminal preference exists.
    pub preferred_ids: Vec<String>,
    /// Maximum number of eligible records retained in the result.
    pub max_candidates: usize,
}

impl TerminalProbeConfig {
    /// Construct a discovery policy without machine-specific defaults.
    pub fn new(
        require_available: bool,
        require_interactive: bool,
        require_pty: bool,
        allowed_kinds: Option<BTreeSet<TerminalKind>>,
        preferred_ids: Vec<String>,
        max_candidates: usize,
    ) -> Result<Self, TerminalProbeError> {
        if max_candidates == 0 {
            return Err(TerminalProbeError::InvalidConfig(
                "max_candidates must be greater than zero".to_owned(),
            ));
        }
        if preferred_ids.iter().any(|id| id.trim().is_empty()) {
            return Err(TerminalProbeError::InvalidConfig(
                "preferred_ids cannot contain empty identities".to_owned(),
            ));
        }
        let mut seen = BTreeSet::new();
        if preferred_ids.iter().any(|id| !seen.insert(id)) {
            return Err(TerminalProbeError::InvalidConfig(
                "preferred_ids must be unique".to_owned(),
            ));
        }
        Ok(Self {
            require_available,
            require_interactive,
            require_pty,
            allowed_kinds,
            preferred_ids,
            max_candidates,
        })
    }
}

/// A deterministic discovery result consumed by process admission.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TerminalDiscovery {
    /// Discovery contract version.
    pub contract_version: u32,
    /// All validated host observations in stable identity order.
    pub observed: Vec<TerminalObservation>,
    /// Eligible observations after policy filtering and preference ordering.
    pub eligible: Vec<TerminalObservation>,
    /// Explicitly selected first eligible observation, if one exists.
    pub selected: Option<TerminalObservation>,
}

/// Fail-closed terminal discovery failures.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalProbeError {
    /// Discovery policy is incomplete or contradictory.
    InvalidConfig(String),
    /// A host observation violates the value contract.
    InvalidObservation { terminal_id: String, reason: String },
    /// Two host records claimed the same stable identity.
    DuplicateTerminal { terminal_id: String },
    /// The policy selected no usable terminal.
    NoEligibleTerminal,
}

/// Pure terminal capability filter and selector.
#[derive(Debug, Clone)]
pub struct TerminalProbe {
    config: TerminalProbeConfig,
}

impl TerminalProbe {
    /// Construct a probe from explicit host policy.
    pub fn new(config: TerminalProbeConfig) -> Self {
        Self { config }
    }

    /// Return the immutable discovery policy.
    pub const fn config(&self) -> &TerminalProbeConfig {
        &self.config
    }

    /// Validate, filter, and select injected host observations.
    pub fn discover<I>(&self, observations: I) -> Result<TerminalDiscovery, TerminalProbeError>
    where
        I: IntoIterator<Item = TerminalObservation>,
    {
        let mut observed = observations.into_iter().collect::<Vec<_>>();
        let mut identities = BTreeSet::new();
        for observation in &observed {
            observation.validate()?;
            if !identities.insert(observation.terminal_id.clone()) {
                return Err(TerminalProbeError::DuplicateTerminal {
                    terminal_id: observation.terminal_id.clone(),
                });
            }
        }
        observed.sort_by(|left, right| left.terminal_id.cmp(&right.terminal_id));

        let mut eligible = observed
            .iter()
            .filter(|observation| self.is_eligible(observation))
            .cloned()
            .collect::<Vec<_>>();
        eligible.sort_by_key(|observation| {
            self.config
                .preferred_ids
                .iter()
                .position(|id| id == &observation.terminal_id)
                .unwrap_or(self.config.preferred_ids.len())
        });
        eligible.truncate(self.config.max_candidates);
        let selected = eligible.first().cloned();
        if selected.is_none() {
            return Err(TerminalProbeError::NoEligibleTerminal);
        }
        Ok(TerminalDiscovery {
            contract_version: TERMINAL_PROBE_CONTRACT_VERSION,
            observed,
            eligible,
            selected,
        })
    }

    fn is_eligible(&self, observation: &TerminalObservation) -> bool {
        (!self.config.require_available || observation.available)
            && (!self.config.require_interactive || observation.interactive)
            && (!self.config.require_pty || observation.pty)
            && self
                .config
                .allowed_kinds
                .as_ref()
                .is_none_or(|allowed| allowed.contains(&observation.kind))
    }
}
