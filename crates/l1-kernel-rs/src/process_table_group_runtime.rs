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

use crate::audit::AuditLog;
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

impl From<ProcessConstraintError> for ProcessTableGroupRuntimeError {
    fn from(error: ProcessConstraintError) -> Self {
        Self::Constraints(error)
    }
}

/// Process-group coordinator whose child identity is owned by ProcessTable.
pub struct ProcessTableGroupRuntime {
    groups: Arc<ProcessGroupBook>,
    reaper: ProcessReaper,
    bridge: ProcessTableBridge,
    termination_timeout: Duration,
    audit: Arc<AuditLog>,
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
        Self::new_with_audit(
            process_config,
            max_groups,
            max_members,
            max_processes,
            termination_timeout,
            table,
            Arc::new(AuditLog::new()),
        )
    }

    /// Construct a bounded runtime with a caller-owned audit trail.
    pub fn new_with_audit(
        process_config: ProcessAdapterConfig,
        max_groups: usize,
        max_members: usize,
        max_processes: u32,
        termination_timeout: Duration,
        table: Arc<ProcessTable>,
        audit: Arc<AuditLog>,
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
            audit,
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
        let name = name.into();
        let result = self.groups.create(name.clone(), None, member_limit);
        match &result {
            Ok(group) => self.audit.record_fields(
                "process.group.create",
                "system",
                true,
                "",
                format!(
                    "group={} member_limit={}",
                    group.raw(),
                    member_limit.unwrap_or(0)
                ),
            ),
            Err(_error) => self.audit.record_fields(
                "process.group.create",
                "system",
                false,
                "group creation rejected",
                format!("member_limit={}", member_limit.unwrap_or(0)),
            ),
        }
        Ok(result?)
    }

    /// Spawn direct arguments and admit the ProcessTable handle to a group.
    pub fn spawn_args(
        &self,
        group: ProcessGroupId,
        args: &[String],
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ProcessTableGroupRuntimeError> {
        self.spawn_args_for_agent(group, args, options, "system")
    }

    fn spawn_args_for_agent(
        &self,
        group: ProcessGroupId,
        args: &[String],
        options: Option<&ProcessOptions>,
        agent_id: &str,
    ) -> Result<ProcessHandle, ProcessTableGroupRuntimeError> {
        if let Err(error) = self.ensure_active(group) {
            self.audit.record_fields(
                "process.group.spawn",
                agent_id,
                false,
                "group is not active",
                format!("group={} argc={}", group.raw(), args.len()),
            );
            return Err(error);
        }
        let handle = match self.bridge.spawn_args(args, options) {
            Ok(handle) => handle,
            Err(error) => {
                self.audit.record_fields(
                    "process.group.spawn",
                    agent_id,
                    false,
                    "bridge spawn failed",
                    format!("group={} argc={}", group.raw(), args.len()),
                );
                return Err(error.into());
            }
        };
        if let Err(error) = self.groups.join(group, handle) {
            let cleanup = self
                .bridge
                .terminate(handle, self.termination_timeout)
                .and_then(|_| self.bridge.reap(handle));
            let runtime_error = match cleanup {
                Ok(_) => ProcessTableGroupRuntimeError::Group(error),
                Err(cleanup_error) => cleanup_error.into(),
            };
            self.audit.record_fields(
                "process.group.spawn",
                agent_id,
                false,
                "group membership or cleanup failed",
                format!("group={} argc={}", group.raw(), args.len()),
            );
            return Err(runtime_error);
        }
        self.audit.record_fields(
            "process.group.spawn",
            agent_id,
            true,
            "",
            format!(
                "group={} handle={} argc={}",
                group.raw(),
                handle.raw(),
                args.len()
            ),
        );
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
        if let Err(error) = self.ensure_active(group) {
            self.audit.record_fields(
                "process.group.spawn.constrained",
                &spec.agent_id,
                false,
                "group is not active",
                format!("group={}", group.raw()),
            );
            return Err(error);
        }
        let evaluator = ProcessConstraintEvaluator::new(policy)
            .map_err(ProcessTableGroupRuntimeError::Constraints);
        let evaluator = match evaluator {
            Ok(evaluator) => evaluator,
            Err(error) => {
                self.audit.record_fields(
                    "process.group.spawn.constrained",
                    &spec.agent_id,
                    false,
                    "constraint policy rejected",
                    format!("group={}", group.raw()),
                );
                return Err(error);
            }
        };
        let admission = match evaluator.admit(spec, terminal) {
            Ok(admission) => admission,
            Err(error) => {
                self.audit.record_fields(
                    "process.group.spawn.constrained",
                    &spec.agent_id,
                    false,
                    "constraint admission rejected",
                    format!("group={}", group.raw()),
                );
                return Err(error.into());
            }
        };
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
            let error = ProcessTableGroupRuntimeError::Constraints(
                ProcessConstraintError::Violations(option_violations),
            );
            self.audit.record_fields(
                "process.group.spawn.constrained",
                &spec.agent_id,
                false,
                "adapter options mismatch",
                format!("group={}", group.raw()),
            );
            return Err(error);
        }
        self.spawn_args_for_agent(group, &admission.argv, options, &spec.agent_id)
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
            self.audit.record_fields(
                "process.group.spawn.gate",
                &request.gate.agent_id,
                false,
                "capability or identity mismatch",
                format!(
                    "tool={} expected={PROCESS_SPAWN_CAPABILITY}",
                    request.gate.tool
                ),
            );
            return Err(ProcessTableGroupRuntimeError::GateBlocked(
                GateDecision::Block,
            ));
        }
        let decision = request.gatechain.check(request.gate);
        if !decision.allowed {
            self.audit.record_fields(
                "process.group.spawn.gate",
                &request.gate.agent_id,
                false,
                format!("gate decision {}", decision.decision.as_str()),
                format!("tool={PROCESS_SPAWN_CAPABILITY}"),
            );
            return Err(ProcessTableGroupRuntimeError::GateBlocked(
                decision.decision,
            ));
        }
        self.audit.record_fields(
            "process.group.spawn.gate",
            &request.gate.agent_id,
            true,
            "",
            format!(
                "tool={PROCESS_SPAWN_CAPABILITY} decision={}",
                decision.decision.as_str()
            ),
        );
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
        let result = self.reaper.request_stop(group, reason);
        match &result {
            Ok(plan) => self.audit.record_fields(
                "process.group.stop",
                "system",
                true,
                "",
                format!(
                    "group={} generation={} members={}",
                    plan.group_id,
                    plan.generation,
                    plan.handles.len()
                ),
            ),
            Err(_error) => self.audit.record_fields(
                "process.group.stop",
                "system",
                false,
                "stop request rejected",
                format!("group={}", group.raw()),
            ),
        }
        Ok(result?)
    }

    /// Request a stop and validate the host adapter's signal report.
    pub fn request_stop_with_signal<P: ProcessGroupSignalPort>(
        &self,
        group: ProcessGroupId,
        reason: impl Into<String>,
        signal_port: &P,
    ) -> Result<ProcessGroupSignalReport, ProcessTableGroupRuntimeError> {
        let plan = self.request_stop(group, reason)?;
        let report = match signal_port.send_stop(&plan) {
            Ok(report) => report,
            Err(error) => {
                self.audit.record_fields(
                    "process.group.signal",
                    "system",
                    false,
                    "host signal adapter rejected",
                    format!("group={} generation={}", plan.group_id, plan.generation),
                );
                return Err(ProcessTableGroupRuntimeError::Signal(
                    ProcessGroupSignalError::Adapter(error),
                ));
            }
        };
        if let Err(error) = report.validate_for(&plan) {
            self.audit.record_fields(
                "process.group.signal",
                "system",
                false,
                "host signal report invalid",
                format!("group={} generation={}", plan.group_id, plan.generation),
            );
            return Err(ProcessTableGroupRuntimeError::Signal(error));
        }
        self.audit.record_fields(
            "process.group.signal",
            "system",
            true,
            "",
            format!(
                "group={} generation={} attempted={} delivered={}",
                report.group_id, report.generation, report.attempted, report.delivered
            ),
        );
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

    /// Return the audit trail used for process-group admission evidence.
    pub fn audit(&self) -> Arc<AuditLog> {
        Arc::clone(&self.audit)
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
