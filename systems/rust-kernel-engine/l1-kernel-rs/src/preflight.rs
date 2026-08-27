//! Read-only entry preflight for the independent Rust kernel.
//!
//! The preflight boundary combines declarative assembly validation with an
//! injected state observation. It never probes the host, creates files,
//! starts workers, executes boot callbacks, or selects a Python fallback.

use serde::{Deserialize, Serialize};

use crate::assembly::{AssemblyError, AssemblySnapshot, AssemblySpec, KernelAssembly};
use crate::state_layout::{StateAction, StateDecision, StateLayoutError, StateProbe};

/// Version of the read-only entry preflight contract.
pub const PREFLIGHT_CONTRACT_VERSION: u32 = 1;

/// JSON input accepted by the preflight entrypoint.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PreflightRequest {
    /// Declarative Rust assembly metadata selected by the host.
    pub assembly: AssemblySpec,
    /// Host observations used only to choose the next state action.
    pub state_probe: StateProbe,
}

/// Coarse disposition for an operator or future entry adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PreflightDisposition {
    /// The root can be initialized or resumed after the caller's own policy.
    Ready,
    /// The root requires an explicit recovery procedure before boot.
    RecoveryRequired,
    /// The root requires a versioned migration before boot.
    MigrationRequired,
    /// The root or assembly is incompatible and must not be mutated.
    Rejected,
}

impl PreflightDisposition {
    /// Derive the operator disposition from a state action.
    pub const fn from_action(action: StateAction) -> Self {
        match action {
            StateAction::Initialize | StateAction::Resume => Self::Ready,
            StateAction::Recover => Self::RecoveryRequired,
            StateAction::Migrate => Self::MigrationRequired,
            StateAction::Reject => Self::Rejected,
        }
    }
}

/// Stable read-only report emitted by the Rust entry preflight.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PreflightReport {
    /// Preflight contract version.
    pub contract_version: u32,
    /// Assembly metadata after validation and deterministic ordering.
    pub assembly: AssemblySnapshot,
    /// State action selected from the injected host observation.
    pub state_decision: StateDecision,
    /// Coarse operator disposition for the selected action.
    pub disposition: PreflightDisposition,
}

/// Fail-closed preflight errors.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PreflightError {
    /// Declarative assembly metadata is invalid.
    Assembly(AssemblyError),
    /// Host state observations are malformed.
    State(StateLayoutError),
}

/// Validate assembly and state observations without applying side effects.
pub fn inspect(request: PreflightRequest) -> Result<PreflightReport, PreflightError> {
    let assembly = KernelAssembly::assemble(request.assembly).map_err(PreflightError::Assembly)?;
    let state_decision = assembly
        .state_decision(&request.state_probe)
        .map_err(PreflightError::State)?;
    Ok(PreflightReport {
        contract_version: PREFLIGHT_CONTRACT_VERSION,
        assembly: assembly.snapshot(),
        disposition: PreflightDisposition::from_action(state_decision.action),
        state_decision,
    })
}
