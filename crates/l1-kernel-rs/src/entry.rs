//! Explicit Rust kernel entry coordination for the clean-break build.
//!
//! This module turns a caller-supplied assembly specification and deployment
//! configuration into a bounded one-shot entry operation. It owns no Python,
//! PTY, provider, AgentLoop execution, or default production selection.

use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::assembly::AssemblySpec;
use crate::recovery::{RecoveryAction, RecoveryDecision};
use crate::runtime::{KernelRuntime, RuntimeConfig, RuntimeError, RuntimeSnapshot};
use crate::worker::WorkerConfig;

/// Version of the explicit Rust entry coordination contract.
pub const ENTRY_CONTRACT_VERSION: u32 = 1;
/// Maximum JSON request size accepted by the one-shot entry binary.
pub const MAX_ENTRY_REQUEST_BYTES: usize = 1024 * 1024;

/// One-shot operation selected by the host.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EntryOperation {
    /// Open the persistent root and return its recovery decision only.
    Inspect,
    /// Boot the runtime, capture the active snapshot, then shut it down cleanly.
    BootOnce,
}

/// JSON-safe deployment values for the Rust runtime.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct EntryRuntimeConfig {
    /// Maximum number of runtime task/process slots.
    pub max_processes: u32,
    /// Number of runtime task-book and session shards.
    pub shard_count: u32,
    /// Minimum resident workers.
    pub min_workers: usize,
    /// Maximum resident workers.
    pub max_workers: usize,
    /// Maximum pending worker tasks.
    pub queue_size: usize,
    /// Worker idle retirement threshold in milliseconds.
    pub idle_timeout_ms: u64,
    /// Clean-shutdown wait budget in milliseconds.
    pub shutdown_timeout_ms: u64,
}

impl EntryRuntimeConfig {
    /// Validate and convert explicit wire values into runtime deployment values.
    pub fn runtime_config(self) -> Result<RuntimeConfig, EntryError> {
        if self.max_processes == 0 || self.shard_count == 0 {
            return Err(EntryError::InvalidConfig(
                "max_processes and shard_count must be greater than zero".to_owned(),
            ));
        }
        if self.min_workers == 0 || self.max_workers == 0 {
            return Err(EntryError::InvalidConfig(
                "worker counts must be greater than zero".to_owned(),
            ));
        }
        if self.max_workers < self.min_workers {
            return Err(EntryError::InvalidConfig(
                "max_workers cannot be less than min_workers".to_owned(),
            ));
        }
        if self.queue_size == 0 {
            return Err(EntryError::InvalidConfig(
                "queue_size must be greater than zero".to_owned(),
            ));
        }
        if self.idle_timeout_ms == 0 || self.shutdown_timeout_ms == 0 {
            return Err(EntryError::InvalidConfig(
                "idle_timeout_ms and shutdown_timeout_ms must be greater than zero".to_owned(),
            ));
        }
        Ok(RuntimeConfig::new(
            self.max_processes,
            self.shard_count,
            WorkerConfig::new(
                self.min_workers,
                self.max_workers,
                self.queue_size,
                Duration::from_millis(self.idle_timeout_ms),
            ),
        ))
    }

    /// Return the explicit clean-shutdown timeout.
    pub fn shutdown_timeout(self) -> Duration {
        Duration::from_millis(self.shutdown_timeout_ms)
    }
}

/// Input to the explicit Rust entry coordinator.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EntryRequest {
    /// Entry contract version.
    pub contract_version: u32,
    /// Declarative assembly selected by the host.
    pub assembly: AssemblySpec,
    /// Explicit runtime and shutdown limits.
    pub runtime: EntryRuntimeConfig,
    /// One-shot operation to execute.
    pub operation: EntryOperation,
    /// Exact recovery decision acknowledged after caller-owned rebind work.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recovery_ack: Option<RecoveryDecision>,
}

/// Stable report returned by an entry operation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EntryReport {
    /// Entry contract version.
    pub contract_version: u32,
    /// Operation that was executed.
    pub operation: EntryOperation,
    /// Recovery decision observed before any optional acknowledgement.
    pub recovery: RecoveryDecision,
    /// Whether the exact recovery decision was acknowledged in this run.
    pub recovery_acknowledged: bool,
    /// Active snapshot captured by `boot_once`, if requested.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub boot: Option<RuntimeSnapshot>,
    /// Clean halted snapshot captured after `boot_once`, if requested.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shutdown: Option<RuntimeSnapshot>,
}

/// Fail-closed errors at the explicit entry boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EntryError {
    /// The request contract or deployment values are invalid.
    InvalidConfig(String),
    /// The runtime could not open, boot, or shut down.
    Runtime(String),
    /// Caller must perform recovery work and acknowledge this exact decision.
    RecoveryRequired(RecoveryDecision),
    /// The supplied acknowledgement is not the current decision.
    RecoveryDecisionStale,
    /// Acknowledgement was supplied for a clean or rejected root.
    RecoveryNotRequired(RecoveryAction),
}

impl std::fmt::Display for EntryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidConfig(message) => write!(formatter, "invalid entry config: {message}"),
            Self::Runtime(message) => write!(formatter, "entry runtime failed: {message}"),
            Self::RecoveryRequired(decision) => write!(
                formatter,
                "recovery acknowledgement required for generation {} ({})",
                decision.generation,
                decision.action.as_str()
            ),
            Self::RecoveryDecisionStale => write!(formatter, "recovery acknowledgement is stale"),
            Self::RecoveryNotRequired(action) => {
                write!(
                    formatter,
                    "recovery acknowledgement is not required for {}",
                    action.as_str()
                )
            }
        }
    }
}

impl std::error::Error for EntryError {}

/// Execute one explicit entry operation against a Rust-owned state root.
pub fn execute(request: EntryRequest) -> Result<EntryReport, EntryError> {
    if request.contract_version != ENTRY_CONTRACT_VERSION {
        return Err(EntryError::InvalidConfig(format!(
            "unsupported entry contract version {}",
            request.contract_version
        )));
    }
    let runtime_config = request.runtime.runtime_config()?;
    let state_root = request.assembly.state_root.clone();
    let runtime =
        KernelRuntime::open_persistent(request.assembly, runtime_config, Path::new(&state_root))
            .map_err(runtime_error)?;
    let recovery = runtime.recovery_decision().map_err(runtime_error)?;
    let recovery_acknowledged = match request.recovery_ack {
        None if recovery.action == RecoveryAction::RecoverUnclean => {
            return Err(EntryError::RecoveryRequired(recovery));
        }
        None => false,
        Some(ack) => {
            if recovery.action != RecoveryAction::RecoverUnclean {
                return Err(EntryError::RecoveryNotRequired(recovery.action));
            }
            if ack != recovery {
                return Err(EntryError::RecoveryDecisionStale);
            }
            runtime.acknowledge_recovery(&ack).map_err(runtime_error)?;
            true
        }
    };

    let (boot, shutdown) = match request.operation {
        EntryOperation::Inspect => (None, None),
        EntryOperation::BootOnce => {
            let boot = runtime.boot().map_err(runtime_error)?;
            let shutdown = runtime
                .shutdown(Some(request.runtime.shutdown_timeout()))
                .map_err(runtime_error)?;
            (Some(boot), Some(shutdown))
        }
    };
    Ok(EntryReport {
        contract_version: ENTRY_CONTRACT_VERSION,
        operation: request.operation,
        recovery,
        recovery_acknowledged,
        boot,
        shutdown,
    })
}

fn runtime_error(error: RuntimeError) -> EntryError {
    EntryError::Runtime(format!("{error:?}"))
}
