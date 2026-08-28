//! Read-only recovery and cutover decisions for the Rust kernel candidate.
//!
//! This module turns lifecycle state and a validated execution checkpoint into
//! an explicit decision. It never mutates books, boots workers, imports Python
//! state, or selects a production fallback.

use serde::{Deserialize, Serialize};

use crate::execution_store::ExecutionStoreDocument;
use crate::lifecycle::LifecycleState;

/// Action selected by the recovery trigger at a Rust-owned entry boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryAction {
    /// No durable execution state exists and a fresh root may be initialized.
    Fresh,
    /// A clean execution document may be resumed after explicit boot.
    ResumeClean,
    /// An unclean execution document requires caller-owned recovery steps.
    RecoverUnclean,
    /// Lifecycle and checkpoint state disagree or the runtime is mid-flight.
    Reject,
}

impl RecoveryAction {
    /// Return the stable wire spelling used by adapters and evidence reports.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Fresh => "fresh",
            Self::ResumeClean => "resume_clean",
            Self::RecoverUnclean => "recover_unclean",
            Self::Reject => "reject",
        }
    }
}

/// Deterministic recovery decision with no side effects.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RecoveryDecision {
    /// Selected action.
    pub action: RecoveryAction,
    /// Lifecycle state observed when the decision was made.
    pub lifecycle: LifecycleState,
    /// Execution checkpoint generation, or zero for a fresh root.
    pub generation: u64,
    /// Human-readable reason for diagnostics and audit projection.
    pub reason: String,
}

/// Pure recovery trigger for a validated Rust execution checkpoint.
pub struct RecoveryTrigger;

impl RecoveryTrigger {
    /// Evaluate whether a root is fresh, resumable, recoverable, or rejected.
    pub fn decide(
        lifecycle: LifecycleState,
        document: Option<&ExecutionStoreDocument>,
    ) -> RecoveryDecision {
        let Some(document) = document else {
            return if lifecycle == LifecycleState::Halted {
                Self::decision(
                    RecoveryAction::Fresh,
                    lifecycle,
                    0,
                    "no execution checkpoint is present",
                )
            } else {
                Self::decision(
                    RecoveryAction::Reject,
                    lifecycle,
                    0,
                    "missing execution checkpoint requires a halted lifecycle",
                )
            };
        };
        if document.generation == 0
            && document.clean_shutdown
            && document.sessions.is_empty()
            && document.terminals.is_empty()
            && document.loops.is_empty()
        {
            return if lifecycle == LifecycleState::Halted {
                Self::decision(
                    RecoveryAction::Fresh,
                    lifecycle,
                    document.generation,
                    "execution checkpoint is empty",
                )
            } else {
                Self::decision(
                    RecoveryAction::Reject,
                    lifecycle,
                    document.generation,
                    "empty execution checkpoint requires a halted lifecycle",
                )
            };
        }
        match (lifecycle, document.clean_shutdown) {
            (LifecycleState::Halted, true) => Self::decision(
                RecoveryAction::ResumeClean,
                lifecycle,
                document.generation,
                "clean execution checkpoint is resumable",
            ),
            (LifecycleState::Crashed, false) => Self::decision(
                RecoveryAction::RecoverUnclean,
                lifecycle,
                document.generation,
                "unclean execution checkpoint requires explicit recovery",
            ),
            _ => Self::decision(
                RecoveryAction::Reject,
                lifecycle,
                document.generation,
                "lifecycle and execution checkpoint state disagree",
            ),
        }
    }

    /// Compute the recovery decision for one action.
    fn decision(
        action: RecoveryAction,
        lifecycle: LifecycleState,
        generation: u64,
        reason: &str,
    ) -> RecoveryDecision {
        RecoveryDecision {
            action,
            lifecycle,
            generation,
            reason: reason.to_owned(),
        }
    }
}
