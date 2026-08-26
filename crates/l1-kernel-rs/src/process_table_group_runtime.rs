//! ProcessTable-authoritative process-group coordination candidate.
//!
//! This module joins the typed process-group book to [`ProcessTableBridge`].
//! The bridge owns the host child and the ProcessTable row, while the group
//! book owns only membership and stop-generation state. A terminal outcome is
//! published to the group only after the bridge has jointly observed and
//! reaped the child and table row.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::contract::{ProcessOptions, ProcessResult};
use crate::gatechain::GateDecision;
use crate::process::{ProcessTable, ProcessTableConfig};
use crate::process_adapter::ProcessAdapterConfig;
use crate::process_bridge::{ProcessBridgeError, ProcessTableBridge};
use crate::process_constraints::{
    AgentProcessPolicy, AgentProcessSpec, ProcessConstraintError, ProcessConstraintEvaluator,
    ProcessConstraintViolation,
};
use crate::process_group::{
    MemberTerminal, ProcessGroupBook, ProcessGroupError, ProcessGroupId, ProcessGroupSignalError,
    ProcessGroupSignalPort, ProcessGroupSignalReport, ProcessGroupSnapshot, ProcessGroupState,
    ProcessGroupTerminationPlan, ProcessReaper, ReaperBudget, ReaperObservation, ReaperReport,
};
use crate::process_group_runtime::{GatedProcessAdmission, PROCESS_SPAWN_CAPABILITY};
use crate::substrate::ProcessHandle;

/// Version of the ProcessTable-authoritative group runtime contract.
pub const PROCESS_TABLE_GROUP_RUNTIME_CONTRACT_VERSION: u32 = 1;

/// Result of one ProcessTable-authoritative stop and reap pass.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessTableGroupDrainReport {
    /// Active groups that accepted a stop request.
    pub groups_requested: u64,
    /// Groups already draining when the pass began.
    pub groups_already_draining: u64,
    /// Groups inspected by the bounded reaper.
    pub groups_inspected: u64,
    /// Member handles inspected by the bounded reaper.
    pub members_inspected: u64,
    /// Members reaped from both ProcessTable and the group book.
    pub reaped: u64,
    /// Live members left for a later caller pass.
    pub pending: u64,
    /// Members removed by another owner before observation.
    pub unavailable: u64,
    /// Ownership or lifecycle errors observed during the pass.
    pub errors: u64,
    /// Groups still draining after the pass.
    pub remaining_groups: u64,
    /// Members still owned by those groups.
    pub remaining_members: u64,
    /// Whether no group or member ownership remains.
    pub complete: bool,
}

/// Fail-closed errors from the ProcessTable-authoritative group runtime.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProcessTableGroupRuntimeError {
    /// The group book rejected an ownership or lifecycle operation.
    Group(ProcessGroupError),
    /// The ProcessTable bridge rejected a host-child or table operation.
    Bridge(ProcessBridgeError),
    /// The explicit process constraint evaluator rejected admission.
    Constraints(ProcessConstraintError),
    /// The capability or identity gate denied admission.
    GateBlocked(GateDecision),
    /// The host signal adapter rejected or misreported a stop plan.
    Signal(ProcessGroupSignalError),
}

impl From<ProcessGroupError> for ProcessTableGroupRuntimeError {
    fn from(error: ProcessGroupError) -> Self {
        Self::Group(error)
    }
}

impl From<ProcessBridgeError> for ProcessTableGroupRuntimeError {
    fn from(error: ProcessBridgeError) -> Self {
        Self::Bridge(error)
    }
}

/// Process-group coordinator whose child identity is owned by ProcessTable.
pub struct ProcessTableGroupRuntime {
    groups: Arc<ProcessGroupBook>,
    reaper: ProcessReaper,
    bridge: ProcessTableBridge,
    termination_timeout: Duration,
}

impl ProcessTableGroupRuntime {
    /// Construct a bounded runtime with an explicit ProcessTable authority.
    pub fn new(
        process_config: ProcessAdapterConfig,
        max_groups: usize,
        max_members: usize,
        max_processes: u32,
        termination_timeout: Duration,
        table: Arc<ProcessTable>,
    ) -> Result<Self, ProcessTableGroupRuntimeError> {
        let groups = Arc::new(ProcessGroupBook::new(max_groups, max_members)?);
        let bridge = ProcessTableBridge::new(process_config, max_processes, table)
            .map_err(|error| ProcessTableGroupRuntimeError::Bridge(error.into()))?;
        let reaper = ProcessReaper::new(Arc::clone(&groups));
        Ok(Self {
            groups,
            reaper,
            bridge,
            termination_timeout,
        })
    }

    /// Construct with a standard ProcessTable configuration and adapter.
    pub fn standard(
        max_groups: usize,
        max_members: usize,
        max_processes: u32,
        termination_timeout: Duration,
        table_config: ProcessTableConfig,
    ) -> Result<Self, ProcessTableGroupRuntimeError> {
        let table = Arc::new(ProcessTable::new(table_config));
        Self::new(
            ProcessAdapterConfig::standard(),
            max_groups,
            max_members,
            max_processes,
            termination_timeout,
            table,
        )
    }

    /// Return the ProcessTable-authoritative bridge for host adapters.
    pub const fn bridge(&self) -> &ProcessTableBridge {
        &self.bridge
    }

    /// Return the group book for deterministic snapshots and inspection.
    pub fn groups(&self) -> Arc<ProcessGroupBook> {
        Arc::clone(&self.groups)
    }

    /// Create an active group that can receive ProcessTable handles.
    pub fn create_group(
        &self,
        name: impl Into<String>,
        member_limit: Option<usize>,
    ) -> Result<ProcessGroupId, ProcessTableGroupRuntimeError> {
        Ok(self.groups.create(name, None, member_limit)?)
    }

    /// Spawn direct arguments and admit the ProcessTable handle to a group.
    pub fn spawn_args(
        &self,
        group: ProcessGroupId,
        args: &[String],
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ProcessTableGroupRuntimeError> {
        self.ensure_active(group)?;
        let handle = self.bridge.spawn_args(args, options)?;
        if let Err(error) = self.groups.join(group, handle) {
            self.bridge.terminate(handle, self.termination_timeout)?;
            self.bridge.reap(handle)?;
            return Err(ProcessTableGroupRuntimeError::Group(error));
        }
        Ok(handle)
    }

    /// Evaluate hard process constraints before admitting a child to a group.
    pub fn spawn_constrained(
        &self,
        group: ProcessGroupId,
        spec: &AgentProcessSpec,
        policy: AgentProcessPolicy,
        terminal: Option<&crate::terminal_probe::TerminalObservation>,
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ProcessTableGroupRuntimeError> {
        self.ensure_active(group)?;
        let evaluator = ProcessConstraintEvaluator::new(policy)
            .map_err(ProcessTableGroupRuntimeError::Constraints)?;
        let admission = evaluator
            .admit(spec, terminal)
            .map_err(ProcessTableGroupRuntimeError::Constraints)?;
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
            return Err(ProcessTableGroupRuntimeError::Constraints(
                ProcessConstraintError::Violations(option_violations),
            ));
        }
        self.spawn_args(group, &admission.argv, options)
    }

    /// Evaluate the capability gate and hard constraints before spawning.
    pub fn spawn_gated_constrained(
        &self,
        group: ProcessGroupId,
        request: GatedProcessAdmission<'_>,
    ) -> Result<ProcessHandle, ProcessTableGroupRuntimeError> {
        if request.gate.tool != PROCESS_SPAWN_CAPABILITY
            || request.gate.agent_id != request.spec.agent_id
        {
            return Err(ProcessTableGroupRuntimeError::GateBlocked(
                GateDecision::Block,
            ));
        }
        let decision = request.gatechain.check(request.gate);
        if !decision.allowed {
            return Err(ProcessTableGroupRuntimeError::GateBlocked(
                decision.decision,
            ));
        }
        self.spawn_constrained(
            group,
            request.spec,
            request.policy,
            request.terminal,
            request.options,
        )
    }

    /// Request a deterministic stop without touching host processes.
    pub fn request_stop(
        &self,
        group: ProcessGroupId,
        reason: impl Into<String>,
    ) -> Result<ProcessGroupTerminationPlan, ProcessTableGroupRuntimeError> {
        Ok(self.reaper.request_stop(group, reason)?)
    }

    /// Request a stop and validate the host adapter's signal report.
    pub fn request_stop_with_signal<P: ProcessGroupSignalPort>(
        &self,
        group: ProcessGroupId,
        reason: impl Into<String>,
        signal_port: &P,
    ) -> Result<ProcessGroupSignalReport, ProcessTableGroupRuntimeError> {
        let plan = self.request_stop(group, reason)?;
        let report = signal_port.send_stop(&plan).map_err(|error| {
            ProcessTableGroupRuntimeError::Signal(ProcessGroupSignalError::Adapter(error))
        })?;
        report
            .validate_for(&plan)
            .map_err(ProcessTableGroupRuntimeError::Signal)?;
        Ok(report)
    }

    /// Run one non-blocking bounded sweep over draining ProcessTable groups.
    pub fn sweep(&self, budget: ReaperBudget) -> ReaperReport {
        self.sweep_with_timeout(budget, Duration::ZERO)
    }

    /// Run one bounded sweep with an explicit child termination deadline.
    pub fn sweep_with_timeout(&self, budget: ReaperBudget, timeout: Duration) -> ReaperReport {
        self.reaper
            .sweep(budget, |handle| self.observe_and_reap(handle, timeout))
    }

    /// Request all active groups to stop and run one caller-bounded sweep.
    pub fn drain_once(
        &self,
        reason: impl Into<String>,
        budget: ReaperBudget,
        timeout: Duration,
    ) -> Result<ProcessTableGroupDrainReport, ProcessTableGroupRuntimeError> {
        let reason = reason.into();
        let mut report = ProcessTableGroupDrainReport::default();
        for group in self.groups.snapshots() {
            match group.state {
                ProcessGroupState::Active => {
                    self.request_stop(group_id(&group)?, reason.clone())?;
                    report.groups_requested = report.groups_requested.saturating_add(1);
                }
                ProcessGroupState::Draining => {
                    report.groups_already_draining =
                        report.groups_already_draining.saturating_add(1);
                }
                ProcessGroupState::Stopped | ProcessGroupState::Failed => {}
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
            if group.state == ProcessGroupState::Draining {
                report.remaining_groups = report.remaining_groups.saturating_add(1);
            }
            report.remaining_members = report
                .remaining_members
                .saturating_add(group.members.len() as u64);
        }
        report.complete = report.remaining_groups == 0 && report.remaining_members == 0;
        Ok(report)
    }

    /// Return one deterministic group snapshot.
    pub fn snapshot(
        &self,
        group: ProcessGroupId,
    ) -> Result<ProcessGroupSnapshot, ProcessTableGroupRuntimeError> {
        Ok(self.groups.snapshot(group)?)
    }

    fn ensure_active(&self, group: ProcessGroupId) -> Result<(), ProcessTableGroupRuntimeError> {
        let state = self.groups.state(group)?;
        if state == ProcessGroupState::Active {
            Ok(())
        } else {
            Err(ProcessTableGroupRuntimeError::Group(
                ProcessGroupError::InvalidState(state),
            ))
        }
    }

    fn observe_and_reap(&self, handle: ProcessHandle, timeout: Duration) -> ReaperObservation {
        match self.bridge.wait(handle, Duration::ZERO) {
            Ok(crate::managed_process::ManagedWaitResult::Finished(result)) => {
                self.reap_terminal(handle, result, false)
            }
            Ok(crate::managed_process::ManagedWaitResult::Pending) => {
                if timeout.is_zero() {
                    return ReaperObservation::Pending;
                }
                match self.bridge.terminate(handle, timeout) {
                    Ok(result) => {
                        let killed = self
                            .bridge
                            .snapshot(handle)
                            .map(|snapshot| {
                                snapshot.managed_state
                                    == crate::managed_process::ManagedProcessState::Killed
                            })
                            .unwrap_or(true);
                        self.reap_terminal(handle, result, killed)
                    }
                    Err(ProcessBridgeError::Managed(
                        crate::managed_process::ManagedProcessError::TerminationTimeout,
                    )) => ReaperObservation::Pending,
                    Err(ProcessBridgeError::TableUnavailable)
                    | Err(ProcessBridgeError::Managed(
                        crate::managed_process::ManagedProcessError::UnknownHandle,
                    )) => ReaperObservation::Unavailable,
                    Err(_) => ReaperObservation::Pending,
                }
            }
            Err(ProcessBridgeError::TableUnavailable)
            | Err(ProcessBridgeError::Managed(
                crate::managed_process::ManagedProcessError::UnknownHandle,
            )) => ReaperObservation::Unavailable,
            Err(_) => ReaperObservation::Pending,
        }
    }

    fn reap_terminal(
        &self,
        handle: ProcessHandle,
        result: ProcessResult,
        killed: bool,
    ) -> ReaperObservation {
        if self.bridge.reap(handle).is_err() {
            return ReaperObservation::Pending;
        }
        if killed {
            return ReaperObservation::Terminal(MemberTerminal::Cancelled(
                "group termination requested".to_owned(),
            ));
        }
        if result.timed_out {
            ReaperObservation::Terminal(MemberTerminal::Cancelled(
                "process deadline elapsed".to_owned(),
            ))
        } else if result.error_kind.is_empty() {
            ReaperObservation::Terminal(MemberTerminal::Exited(result.returncode))
        } else {
            ReaperObservation::Terminal(MemberTerminal::Failed(result.stderr))
        }
    }
}

fn group_id(
    snapshot: &ProcessGroupSnapshot,
) -> Result<ProcessGroupId, ProcessTableGroupRuntimeError> {
    ProcessGroupId::new(snapshot.group_id).ok_or(ProcessTableGroupRuntimeError::Group(
        ProcessGroupError::UnknownGroup,
    ))
}
