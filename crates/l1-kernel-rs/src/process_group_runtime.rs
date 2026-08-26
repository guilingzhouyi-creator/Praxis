//! Rust-native coordination boundary for managed children and process groups.
//!
//! This module is deliberately narrower than a production process supervisor.
//! It composes the typed [`ProcessGroupBook`] with [`ManagedProcessBook`],
//! keeping group state and OS-child ownership consistent while a caller drives
//! bounded reaper sweeps. PTYs, OS process-group signals, AgentLoop routing,
//! and background shutdown authority remain outside this candidate.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::contract::ProcessOptions;
use crate::gatechain::{GateChain, GateDecision, GateRequest};
use crate::managed_process::{
    ManagedProcessBook, ManagedProcessError, ManagedProcessState, ManagedWaitResult,
};
use crate::process_adapter::ProcessAdapterConfig;
use crate::process_constraints::{
    AgentProcessPolicy, AgentProcessSpec, ProcessConstraintError, ProcessConstraintEvaluator,
    ProcessConstraintViolation,
};
use crate::process_group::{
    MemberTerminal, ProcessGroupBook, ProcessGroupError, ProcessGroupId, ProcessGroupSnapshot,
    ProcessGroupTerminationPlan, ProcessReaper, ReaperBudget, ReaperObservation, ReaperReport,
};
use crate::substrate::ProcessHandle;

/// Version of the managed process-group coordination boundary.
pub const PROCESS_GROUP_RUNTIME_CONTRACT_VERSION: u32 = 1;
/// Capability name required for a gated process spawn.
pub const PROCESS_SPAWN_CAPABILITY: &str = "process.spawn";

/// Result of one caller-owned stop request plus bounded reaper sweep.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessGroupDrainReport {
    /// Number of active groups that accepted the stop request.
    pub groups_requested: u64,
    /// Number of groups already draining when this call started.
    pub groups_already_draining: u64,
    /// Number of draining groups inspected by the bounded sweep.
    pub groups_inspected: u64,
    /// Number of member handles inspected by the bounded sweep.
    pub members_inspected: u64,
    /// Number of members jointly reaped by the sweep.
    pub reaped: u64,
    /// Number of live members left for a later caller sweep.
    pub pending: u64,
    /// Number of members unavailable to this owner.
    pub unavailable: u64,
    /// Number of terminal observations rejected by group ownership.
    pub errors: u64,
    /// Number of groups still draining after the sweep.
    pub remaining_groups: u64,
    /// Number of members still owned by those groups.
    pub remaining_members: u64,
    /// Whether every group is stopped or failed and no member remains.
    pub complete: bool,
}

/// Fail-closed errors from the process-group coordination boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProcessGroupRuntimeError {
    /// The group book rejected an ownership or lifecycle operation.
    Group(ProcessGroupError),
    /// The managed process book rejected an OS-child operation.
    Process(ManagedProcessError),
    /// A child could not be cleaned up after group admission failed.
    Cleanup(ManagedProcessError),
    /// The Agent process failed the explicit L1 constraint gate.
    Constraints(ProcessConstraintError),
    /// The capability gate denied the process admission before spawn.
    GateBlocked(GateDecision),
}

/// Caller-owned inputs for GateChain plus hard process admission.
pub struct GatedProcessAdmission<'a> {
    /// Explicit capability gate and audit ledger.
    pub gatechain: &'a GateChain,
    /// Gate request correlated with the process identity.
    pub gate: &'a GateRequest,
    /// Declarative process intent.
    pub spec: &'a AgentProcessSpec,
    /// Hard process policy snapshot.
    pub policy: AgentProcessPolicy,
    /// Host-injected terminal observation, when shell mode is requested.
    pub terminal: Option<&'a crate::terminal_probe::TerminalObservation>,
    /// Adapter options that must match the admitted request.
    pub options: Option<&'a ProcessOptions>,
}

impl From<ProcessGroupError> for ProcessGroupRuntimeError {
    fn from(error: ProcessGroupError) -> Self {
        Self::Group(error)
    }
}

impl From<ManagedProcessError> for ProcessGroupRuntimeError {
    fn from(error: ManagedProcessError) -> Self {
        Self::Process(error)
    }
}

/// Rust-owned process-group coordinator with caller-driven reaping.
pub struct ProcessGroupRuntime {
    groups: Arc<ProcessGroupBook>,
    processes: Arc<ManagedProcessBook>,
    reaper: ProcessReaper,
    termination_timeout: Duration,
}

impl ProcessGroupRuntime {
    /// Construct a bounded coordinator with an explicit child-stop deadline.
    pub fn new(
        process_config: ProcessAdapterConfig,
        max_groups: usize,
        max_members: usize,
        max_processes: u32,
        termination_timeout: Duration,
    ) -> Result<Self, ProcessGroupRuntimeError> {
        let groups = Arc::new(ProcessGroupBook::new(max_groups, max_members)?);
        let processes = Arc::new(
            ManagedProcessBook::new(process_config, max_processes)
                .map_err(ProcessGroupRuntimeError::Process)?,
        );
        let reaper = ProcessReaper::new(Arc::clone(&groups));
        Ok(Self {
            groups,
            processes,
            reaper,
            termination_timeout,
        })
    }

    /// Return the group book for deterministic snapshots and inspection.
    pub fn groups(&self) -> Arc<ProcessGroupBook> {
        Arc::clone(&self.groups)
    }

    /// Return the managed child book for explicit adapter operations.
    pub fn processes(&self) -> Arc<ManagedProcessBook> {
        Arc::clone(&self.processes)
    }

    /// Create an active group that can receive managed child handles.
    pub fn create_group(
        &self,
        name: impl Into<String>,
        member_limit: Option<usize>,
    ) -> Result<ProcessGroupId, ProcessGroupRuntimeError> {
        Ok(self.groups.create(name, None, member_limit)?)
    }

    /// Spawn direct arguments and retain the child in an active group.
    ///
    /// If group admission loses a concurrent lifecycle race, the child is
    /// terminated and reaped before the group error is returned.
    pub fn spawn_args(
        &self,
        group: ProcessGroupId,
        args: &[String],
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ProcessGroupRuntimeError> {
        self.ensure_active(group)?;
        let handle = self
            .processes
            .spawn_args(args, options)
            .map_err(ProcessGroupRuntimeError::Process)?;
        if let Err(error) = self.groups.join(group, handle) {
            return self.cleanup_unadmitted(handle, error);
        }
        Ok(handle)
    }

    /// Evaluate hard Agent constraints before admitting a child to a group.
    ///
    /// The caller supplies the already-probed terminal observation. This path
    /// has no host discovery fallback and therefore cannot silently select a
    /// machine-specific shell. The returned child uses the admitted argv as a
    /// direct argument list; shell requests must include the observation's
    /// invocation prefix in `spec.argv`.
    pub fn spawn_constrained(
        &self,
        group: ProcessGroupId,
        spec: &AgentProcessSpec,
        policy: AgentProcessPolicy,
        terminal: Option<&crate::terminal_probe::TerminalObservation>,
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ProcessGroupRuntimeError> {
        self.ensure_active(group)?;
        let evaluator = ProcessConstraintEvaluator::new(policy)
            .map_err(ProcessGroupRuntimeError::Constraints)?;
        let admission = evaluator
            .admit(spec, terminal)
            .map_err(ProcessGroupRuntimeError::Constraints)?;
        let mut option_violations = Vec::new();
        let expected_executable = admission.argv.first().cloned().unwrap_or_default();
        let actual_executable = options.and_then(|value| value.executable.clone());
        if actual_executable
            .as_deref()
            .is_some_and(|value| value != expected_executable)
        {
            option_violations.push(ProcessConstraintViolation::AdapterExecutableMismatch {
                expected: expected_executable,
                actual: actual_executable,
            });
        }
        let actual_cwd = options.and_then(|value| value.cwd.clone());
        if actual_cwd != spec.cwd {
            option_violations.push(
                ProcessConstraintViolation::AdapterWorkingDirectoryMismatch {
                    expected: spec.cwd.clone(),
                    actual: actual_cwd,
                },
            );
        }
        let expected_keys = spec
            .environment_keys
            .iter()
            .cloned()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        let actual_keys = options
            .and_then(|value| value.env.as_ref())
            .map(|env| env.keys().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        let environment_mismatch = if spec.replaces_environment {
            options.is_none_or(|value| value.env.is_none()) || actual_keys != expected_keys
        } else {
            options.is_some_and(|value| value.env.is_some())
        };
        if environment_mismatch {
            option_violations.push(ProcessConstraintViolation::AdapterEnvironmentMismatch {
                expected: expected_keys,
                actual: actual_keys,
            });
        }
        if !option_violations.is_empty() {
            return Err(ProcessGroupRuntimeError::Constraints(
                ProcessConstraintError::Violations(option_violations),
            ));
        }
        self.spawn_args(group, &admission.argv, options)
    }

    /// Evaluate G1-G5 and hard process constraints before spawning a child.
    ///
    /// The gate and constraint inputs are caller-owned snapshots. A denied
    /// request never reaches the process adapter, and no terminal or shell
    /// defaults are inferred by this coordination layer.
    pub fn spawn_gated_constrained(
        &self,
        group: ProcessGroupId,
        request: GatedProcessAdmission<'_>,
    ) -> Result<ProcessHandle, ProcessGroupRuntimeError> {
        if request.gate.tool != PROCESS_SPAWN_CAPABILITY
            || request.gate.agent_id != request.spec.agent_id
        {
            return Err(ProcessGroupRuntimeError::GateBlocked(GateDecision::Block));
        }
        let decision = request.gatechain.check(request.gate);
        if !decision.allowed {
            return Err(ProcessGroupRuntimeError::GateBlocked(decision.decision));
        }
        self.spawn_constrained(
            group,
            request.spec,
            request.policy,
            request.terminal,
            request.options,
        )
    }

    /// Request a deterministic group stop without touching host processes.
    pub fn request_stop(
        &self,
        group: ProcessGroupId,
        reason: impl Into<String>,
    ) -> Result<ProcessGroupTerminationPlan, ProcessGroupRuntimeError> {
        Ok(self.reaper.request_stop(group, reason)?)
    }

    /// Request all active groups to stop and run one bounded reaper sweep.
    ///
    /// This method is intentionally one-shot: callers own the repeat policy,
    /// timeout budget, and eventual production shutdown authority. It performs
    /// no background work and reports remaining groups/members so a caller can
    /// continue with another bounded invocation.
    pub fn drain_once(
        &self,
        reason: impl Into<String>,
        budget: ReaperBudget,
        timeout: Duration,
    ) -> Result<ProcessGroupDrainReport, ProcessGroupRuntimeError> {
        let reason = reason.into();
        let mut report = ProcessGroupDrainReport::default();
        for group in self.groups.snapshots() {
            match group.state {
                crate::process_group::ProcessGroupState::Active => {
                    self.request_stop(group_id(&group)?, reason.clone())?;
                    report.groups_requested = report.groups_requested.saturating_add(1);
                }
                crate::process_group::ProcessGroupState::Draining => {
                    report.groups_already_draining =
                        report.groups_already_draining.saturating_add(1);
                }
                crate::process_group::ProcessGroupState::Stopped
                | crate::process_group::ProcessGroupState::Failed => {}
            }
        }
        let sweep = self.sweep_with_timeout(budget, timeout);
        report.groups_inspected = sweep.groups_inspected;
        report.members_inspected = sweep.members_inspected;
        report.reaped = sweep.reaped;
        report.pending = sweep.pending;
        report.unavailable = sweep.unavailable;
        report.errors = sweep.errors;
        for group in self.groups.snapshots() {
            if group.state == crate::process_group::ProcessGroupState::Draining {
                report.remaining_groups = report.remaining_groups.saturating_add(1);
            }
            report.remaining_members = report
                .remaining_members
                .saturating_add(group.members.len() as u64);
        }
        report.complete = report.remaining_groups == 0 && report.remaining_members == 0;
        Ok(report)
    }

    /// Run a non-blocking bounded sweep over draining groups.
    pub fn sweep(&self, budget: ReaperBudget) -> ReaperReport {
        self.sweep_with_timeout(budget, Duration::ZERO)
    }

    /// Run a bounded sweep with an explicit child termination deadline.
    pub fn sweep_with_timeout(&self, budget: ReaperBudget, timeout: Duration) -> ReaperReport {
        self.reaper
            .sweep(budget, |handle| self.observe_and_reap(handle, timeout))
    }

    /// Return one deterministic group snapshot.
    pub fn snapshot(
        &self,
        group: ProcessGroupId,
    ) -> Result<ProcessGroupSnapshot, ProcessGroupRuntimeError> {
        Ok(self.groups.snapshot(group)?)
    }

    fn ensure_active(&self, group: ProcessGroupId) -> Result<(), ProcessGroupRuntimeError> {
        let state = self.groups.state(group)?;
        if matches!(state, crate::process_group::ProcessGroupState::Active) {
            Ok(())
        } else {
            Err(ProcessGroupRuntimeError::Group(
                ProcessGroupError::InvalidState(state),
            ))
        }
    }

    fn cleanup_unadmitted(
        &self,
        handle: ProcessHandle,
        group_error: ProcessGroupError,
    ) -> Result<ProcessHandle, ProcessGroupRuntimeError> {
        if let Err(error) = self.processes.terminate(handle, self.termination_timeout) {
            return Err(ProcessGroupRuntimeError::Cleanup(error));
        }
        self.processes
            .reap(handle)
            .map_err(ProcessGroupRuntimeError::Cleanup)?;
        Err(ProcessGroupRuntimeError::Group(group_error))
    }

    fn observe_and_reap(&self, handle: ProcessHandle, timeout: Duration) -> ReaperObservation {
        match self.processes.wait(handle, Duration::ZERO) {
            Ok(ManagedWaitResult::Finished(result)) => self.reap_terminal(handle, result, false),
            Ok(ManagedWaitResult::Pending) => {
                // Zero-deadline sweep is observation-only: a live child is
                // left running (reported Pending), never SIGKILLed — only an
                // explicit termination deadline may terminate live children.
                if timeout.is_zero() {
                    return ReaperObservation::Pending;
                }
                match self.processes.terminate(handle, timeout) {
                    Ok(result) => {
                        let killed = self
                            .processes
                            .snapshot(handle)
                            .map(|snapshot| snapshot.state == ManagedProcessState::Killed)
                            .unwrap_or(true);
                        self.reap_terminal(handle, result, killed)
                    }
                    Err(ManagedProcessError::TerminationTimeout) => ReaperObservation::Pending,
                    Err(ManagedProcessError::UnknownHandle) => ReaperObservation::Unavailable,
                    Err(_) => ReaperObservation::Pending,
                }
            }
            Err(ManagedProcessError::UnknownHandle) => ReaperObservation::Unavailable,
            Err(_) => ReaperObservation::Pending,
        }
    }

    fn reap_terminal(
        &self,
        handle: ProcessHandle,
        result: crate::contract::ProcessResult,
        killed: bool,
    ) -> ReaperObservation {
        if let Err(error) = self.processes.reap(handle) {
            return match error {
                ManagedProcessError::UnknownHandle => ReaperObservation::Unavailable,
                ManagedProcessError::ProcessRunning => ReaperObservation::Pending,
                _ => ReaperObservation::Pending,
            };
        }
        if killed {
            return ReaperObservation::Terminal(MemberTerminal::Cancelled(
                "group termination requested".to_owned(),
            ));
        }
        if result.error_kind.is_empty() && !result.timed_out {
            ReaperObservation::Terminal(MemberTerminal::Exited(result.returncode))
        } else if result.timed_out {
            ReaperObservation::Terminal(MemberTerminal::Cancelled(
                "process deadline elapsed".to_owned(),
            ))
        } else {
            ReaperObservation::Terminal(MemberTerminal::Failed(result.stderr))
        }
    }
}

fn group_id(snapshot: &ProcessGroupSnapshot) -> Result<ProcessGroupId, ProcessGroupRuntimeError> {
    ProcessGroupId::new(snapshot.group_id).ok_or(ProcessGroupRuntimeError::Group(
        ProcessGroupError::UnknownGroup,
    ))
}
