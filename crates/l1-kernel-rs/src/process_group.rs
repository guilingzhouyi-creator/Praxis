//! Rust-native process-group ownership and bounded reaper planning.
//!
//! The group book owns only typed process membership, terminal-state
//! accounting, and deterministic stop plans. It does not send OS signals,
//! create a PTY, or spawn a background reaper. A caller supplies observation
//! results through [`ProcessReaper`], keeping host process control behind an
//! explicit adapter boundary.

use std::collections::{BTreeMap, HashMap};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde::{Deserialize, Serialize};

use crate::substrate::ProcessHandle;

/// Version of the process-group and reaper value contract.
pub const PROCESS_GROUP_CONTRACT_VERSION: u32 = 1;
/// Maximum encoded group-name size accepted by the value boundary.
pub const PROCESS_GROUP_MAX_NAME_BYTES: usize = 128;
/// Maximum members in one group unless a smaller caller limit is supplied.
pub const PROCESS_GROUP_MAX_MEMBERS: usize = 4096;

/// Stable non-zero identifier for a process group.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct ProcessGroupId(u64);

impl ProcessGroupId {
    /// Construct an identifier; zero is reserved as an invalid value.
    pub const fn new(value: u64) -> Option<Self> {
        if value == 0 { None } else { Some(Self(value)) }
    }

    /// Return the stable wire value.
    pub const fn raw(self) -> u64 {
        self.0
    }
}

/// Lifecycle of one owned process group.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessGroupState {
    /// Members may be added or removed.
    Active,
    /// A stop plan exists and no new members may join.
    Draining,
    /// All members reached terminal state and may be reaped.
    Stopped,
    /// The group was closed because its ownership contract failed.
    Failed,
}

impl ProcessGroupState {
    /// Return the stable wire spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Draining => "draining",
            Self::Stopped => "stopped",
            Self::Failed => "failed",
        }
    }
}

/// Terminal outcome supplied by a host process adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "kind", content = "value")]
pub enum MemberTerminal {
    /// Child exited and supplied its return code.
    Exited(i32),
    /// Child failed before a normal exit code was available.
    Failed(String),
    /// Child was cancelled by the caller or host adapter.
    Cancelled(String),
}

/// State retained for one group member.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GroupMemberState {
    /// Member has not yet reached a terminal observation.
    Pending,
    /// Member is being stopped by the current plan.
    Stopping,
    /// Member exited normally with a code.
    Exited { returncode: i32 },
    /// Member failed with a bounded diagnostic.
    Failed { reason: String },
    /// Member was cancelled with a bounded diagnostic.
    Cancelled { reason: String },
}

impl GroupMemberState {
    /// Return whether no further host observation is required.
    pub const fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::Exited { .. } | Self::Failed { .. } | Self::Cancelled { .. }
        )
    }

    /// Return the stable state spelling used by diagnostics.
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Stopping => "stopping",
            Self::Exited { .. } => "exited",
            Self::Failed { .. } => "failed",
            Self::Cancelled { .. } => "cancelled",
        }
    }
}

/// One member in a deterministic group snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessGroupMember {
    /// Generation-safe process identity represented at the wire edge.
    pub handle: u64,
    /// Current group-local lifecycle state.
    pub state: GroupMemberState,
}

/// Public group snapshot with no host process objects.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessGroupSnapshot {
    /// Value contract version.
    pub contract_version: u32,
    /// Stable group identity.
    pub group_id: u64,
    /// Human-readable group label.
    pub name: String,
    /// Maximum members accepted by this group.
    pub member_limit: usize,
    /// Group lifecycle.
    pub state: ProcessGroupState,
    /// Optional leader handle.
    pub leader: Option<u64>,
    /// Monotonic stop-plan generation.
    pub generation: u64,
    /// Last stop or failure reason.
    pub reason: String,
    /// Members sorted by raw handle.
    pub members: Vec<ProcessGroupMember>,
}

/// Deterministic work unit emitted by a stop plan.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessGroupTerminationPlan {
    /// Value contract version.
    pub contract_version: u32,
    /// Group being drained.
    pub group_id: u64,
    /// Stop-plan generation, used to reject stale observations.
    pub generation: u64,
    /// Caller-owned reason for the stop request.
    pub reason: String,
    /// Members in stable raw-handle order.
    pub handles: Vec<u64>,
}

/// Bounded group-book failures.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProcessGroupError {
    /// Group capacity has been reached.
    Capacity,
    /// The requested group does not exist.
    UnknownGroup,
    /// The typed handle is already owned by another group.
    HandleAlreadyGrouped,
    /// The handle is not a member of the requested group.
    UnknownMember,
    /// Group state does not accept the requested operation.
    InvalidState(ProcessGroupState),
    /// Input exceeded the value boundary.
    InvalidInput(&'static str),
    /// An observation belonged to an older stop generation.
    StaleGeneration,
    /// A terminal member cannot be observed twice.
    AlreadyTerminal,
    /// A stopped group still has non-terminal members.
    MembersPending,
}

struct GroupMemberRecord {
    handle: ProcessHandle,
    state: GroupMemberState,
}

struct ProcessGroupRecord {
    id: ProcessGroupId,
    name: String,
    member_limit: usize,
    state: ProcessGroupState,
    leader: Option<ProcessHandle>,
    generation: u64,
    reason: String,
    members: BTreeMap<u64, GroupMemberRecord>,
}

struct GroupBookState {
    groups: BTreeMap<ProcessGroupId, ProcessGroupRecord>,
    handle_groups: HashMap<ProcessHandle, ProcessGroupId>,
    next_id: u64,
}

/// Thread-safe, bounded process-group ownership book.
pub struct ProcessGroupBook {
    max_groups: usize,
    max_members: usize,
    state: Mutex<GroupBookState>,
}

impl ProcessGroupBook {
    /// Create an empty group book with explicit capacities.
    pub fn new(max_groups: usize, max_members: usize) -> Result<Self, ProcessGroupError> {
        if max_groups == 0 {
            return Err(ProcessGroupError::InvalidInput("max_groups"));
        }
        if max_members == 0 || max_members > PROCESS_GROUP_MAX_MEMBERS {
            return Err(ProcessGroupError::InvalidInput("max_members"));
        }
        Ok(Self {
            max_groups,
            max_members,
            state: Mutex::new(GroupBookState {
                groups: BTreeMap::new(),
                handle_groups: HashMap::new(),
                next_id: 1,
            }),
        })
    }

    /// Return the configured group capacity.
    pub const fn max_groups(&self) -> usize {
        self.max_groups
    }

    /// Return the configured aggregate member limit per group.
    pub const fn max_members(&self) -> usize {
        self.max_members
    }

    /// Create an active group and optionally attach its leader.
    pub fn create(
        &self,
        name: impl Into<String>,
        leader: Option<ProcessHandle>,
        member_limit: Option<usize>,
    ) -> Result<ProcessGroupId, ProcessGroupError> {
        let name = name.into();
        validate_name(&name)?;
        let limit = member_limit.unwrap_or(self.max_members);
        if limit == 0 || limit > self.max_members {
            return Err(ProcessGroupError::InvalidInput("member_limit"));
        }
        let mut state = self.lock_state();
        if state.groups.len() >= self.max_groups {
            return Err(ProcessGroupError::Capacity);
        }
        if let Some(handle) = leader
            && state.handle_groups.contains_key(&handle)
        {
            return Err(ProcessGroupError::HandleAlreadyGrouped);
        }
        let id = next_group_id(&mut state)?;
        let mut members = BTreeMap::new();
        if let Some(handle) = leader {
            members.insert(
                handle.raw(),
                GroupMemberRecord {
                    handle,
                    state: GroupMemberState::Pending,
                },
            );
            state.handle_groups.insert(handle, id);
        }
        state.groups.insert(
            id,
            ProcessGroupRecord {
                id,
                name,
                member_limit: limit,
                state: ProcessGroupState::Active,
                leader,
                generation: 0,
                reason: String::new(),
                members,
            },
        );
        Ok(id)
    }

    /// Attach a process handle to an active group.
    pub fn join(&self, id: ProcessGroupId, handle: ProcessHandle) -> Result<(), ProcessGroupError> {
        let mut state = self.lock_state();
        if state.handle_groups.contains_key(&handle) {
            return Err(ProcessGroupError::HandleAlreadyGrouped);
        }
        let group = state
            .groups
            .get_mut(&id)
            .ok_or(ProcessGroupError::UnknownGroup)?;
        if group.state != ProcessGroupState::Active {
            return Err(ProcessGroupError::InvalidState(group.state));
        }
        if group.members.len() >= group.member_limit {
            return Err(ProcessGroupError::Capacity);
        }
        group.members.insert(
            handle.raw(),
            GroupMemberRecord {
                handle,
                state: GroupMemberState::Pending,
            },
        );
        state.handle_groups.insert(handle, id);
        Ok(())
    }

    /// Remove a member while the group is still active.
    pub fn leave(
        &self,
        id: ProcessGroupId,
        handle: ProcessHandle,
    ) -> Result<(), ProcessGroupError> {
        let mut state = self.lock_state();
        {
            let group = state
                .groups
                .get_mut(&id)
                .ok_or(ProcessGroupError::UnknownGroup)?;
            if group.state != ProcessGroupState::Active {
                return Err(ProcessGroupError::InvalidState(group.state));
            }
            if group.members.remove(&handle.raw()).is_none() {
                return Err(ProcessGroupError::UnknownMember);
            }
            if group.leader == Some(handle) {
                group.leader = None;
            }
        }
        state.handle_groups.remove(&handle);
        Ok(())
    }

    /// Request a deterministic, non-blocking stop plan for a group.
    pub fn begin_termination(
        &self,
        id: ProcessGroupId,
        reason: impl Into<String>,
    ) -> Result<ProcessGroupTerminationPlan, ProcessGroupError> {
        let reason = bounded_reason(reason.into());
        let mut state = self.lock_state();
        let group = state
            .groups
            .get_mut(&id)
            .ok_or(ProcessGroupError::UnknownGroup)?;
        match group.state {
            ProcessGroupState::Active => {
                group.state = ProcessGroupState::Draining;
                group.generation = group.generation.saturating_add(1);
                group.reason = reason;
                for member in group.members.values_mut() {
                    if !member.state.is_terminal() {
                        member.state = GroupMemberState::Stopping;
                    }
                }
            }
            ProcessGroupState::Draining => {}
            ProcessGroupState::Stopped | ProcessGroupState::Failed => {
                return Err(ProcessGroupError::InvalidState(group.state));
            }
        }
        Ok(termination_plan(group))
    }

    /// Return the current plan when a group is already draining.
    pub fn termination_plan(
        &self,
        id: ProcessGroupId,
    ) -> Result<ProcessGroupTerminationPlan, ProcessGroupError> {
        let state = self.lock_state();
        let group = state
            .groups
            .get(&id)
            .ok_or(ProcessGroupError::UnknownGroup)?;
        if group.state != ProcessGroupState::Draining {
            return Err(ProcessGroupError::InvalidState(group.state));
        }
        Ok(termination_plan(group))
    }

    /// Observe a terminal result for one member in the current generation.
    pub fn mark_terminal(
        &self,
        id: ProcessGroupId,
        generation: u64,
        handle: ProcessHandle,
        outcome: MemberTerminal,
    ) -> Result<ProcessGroupSnapshot, ProcessGroupError> {
        let mut state = self.lock_state();
        let group = state
            .groups
            .get_mut(&id)
            .ok_or(ProcessGroupError::UnknownGroup)?;
        if group.state != ProcessGroupState::Draining {
            return Err(ProcessGroupError::InvalidState(group.state));
        }
        if group.generation != generation {
            return Err(ProcessGroupError::StaleGeneration);
        }
        let member = group
            .members
            .get_mut(&handle.raw())
            .ok_or(ProcessGroupError::UnknownMember)?;
        if member.handle != handle {
            return Err(ProcessGroupError::UnknownMember);
        }
        if member.state.is_terminal() {
            return Err(ProcessGroupError::AlreadyTerminal);
        }
        member.state = terminal_state(outcome);
        if group
            .members
            .values()
            .all(|member| member.state.is_terminal())
        {
            group.state = ProcessGroupState::Stopped;
        }
        Ok(snapshot(group))
    }

    /// Reap one terminal member after the host has consumed its resources.
    pub fn reap_member(
        &self,
        id: ProcessGroupId,
        handle: ProcessHandle,
    ) -> Result<ProcessGroupSnapshot, ProcessGroupError> {
        let mut state = self.lock_state();
        let result = {
            let group = state
                .groups
                .get_mut(&id)
                .ok_or(ProcessGroupError::UnknownGroup)?;
            let member = group
                .members
                .get(&handle.raw())
                .ok_or(ProcessGroupError::UnknownMember)?;
            if member.handle != handle {
                return Err(ProcessGroupError::UnknownMember);
            }
            if !member.state.is_terminal() {
                return Err(ProcessGroupError::MembersPending);
            }
            group.members.remove(&handle.raw());
            snapshot(group)
        };
        state.handle_groups.remove(&handle);
        Ok(result)
    }

    /// Mark a group failed and make all future operations fail closed.
    pub fn fail(
        &self,
        id: ProcessGroupId,
        reason: impl Into<String>,
    ) -> Result<ProcessGroupSnapshot, ProcessGroupError> {
        let mut state = self.lock_state();
        let group = state
            .groups
            .get_mut(&id)
            .ok_or(ProcessGroupError::UnknownGroup)?;
        group.state = ProcessGroupState::Failed;
        group.generation = group.generation.saturating_add(1);
        group.reason = bounded_reason(reason.into());
        Ok(snapshot(group))
    }

    /// Return one deterministic group snapshot.
    pub fn snapshot(&self, id: ProcessGroupId) -> Result<ProcessGroupSnapshot, ProcessGroupError> {
        let state = self.lock_state();
        state
            .groups
            .get(&id)
            .map(snapshot)
            .ok_or(ProcessGroupError::UnknownGroup)
    }

    /// Return a group lifecycle state without allocating a snapshot.
    pub fn state(&self, id: ProcessGroupId) -> Result<ProcessGroupState, ProcessGroupError> {
        self.lock_state()
            .groups
            .get(&id)
            .map(|group| group.state)
            .ok_or(ProcessGroupError::UnknownGroup)
    }

    /// Return the number of members currently owned by a group.
    pub fn member_count(&self, id: ProcessGroupId) -> Result<usize, ProcessGroupError> {
        self.lock_state()
            .groups
            .get(&id)
            .map(|group| group.members.len())
            .ok_or(ProcessGroupError::UnknownGroup)
    }

    /// Return whether a group owns no process handles.
    pub fn is_empty(&self, id: ProcessGroupId) -> Result<bool, ProcessGroupError> {
        Ok(self.member_count(id)? == 0)
    }

    /// Return all groups sorted by id.
    pub fn snapshots(&self) -> Vec<ProcessGroupSnapshot> {
        self.lock_state().groups.values().map(snapshot).collect()
    }

    /// Return the group owning a typed process handle.
    pub fn group_for_handle(&self, handle: ProcessHandle) -> Option<ProcessGroupId> {
        self.lock_state().handle_groups.get(&handle).copied()
    }

    /// Return all currently draining plans in stable group order.
    pub fn draining_plans(&self, max_groups: usize) -> Vec<ProcessGroupTerminationPlan> {
        if max_groups == 0 {
            return Vec::new();
        }
        self.lock_state()
            .groups
            .values()
            .filter(|group| group.state == ProcessGroupState::Draining)
            .take(max_groups)
            .map(termination_plan)
            .collect()
    }

    fn lock_state(&self) -> MutexGuard<'_, GroupBookState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Bounded observation result supplied by a host adapter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReaperObservation {
    /// The child is still live and must be revisited later.
    Pending,
    /// The child is no longer available to this owner.
    Unavailable,
    /// The child reached a terminal result.
    Terminal(MemberTerminal),
}

/// Caller-controlled sweep limits; zero values are rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReaperBudget {
    /// Maximum draining groups inspected by one sweep.
    pub max_groups: usize,
    /// Maximum members observed by one sweep.
    pub max_members: usize,
}

impl ReaperBudget {
    /// Construct a valid fixed-work budget.
    pub const fn new(max_groups: usize, max_members: usize) -> Result<Self, ProcessGroupError> {
        if max_groups == 0 || max_members == 0 {
            return Err(ProcessGroupError::InvalidInput("reaper_budget"));
        }
        Ok(Self {
            max_groups,
            max_members,
        })
    }
}

/// Summary of one bounded reaper sweep.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReaperReport {
    /// Draining groups considered.
    pub groups_inspected: u64,
    /// Member handles considered.
    pub members_inspected: u64,
    /// Live members left for a later sweep.
    pub pending: u64,
    /// Members that reached a terminal observation and were reaped.
    pub reaped: u64,
    /// Members unavailable to this owner.
    pub unavailable: u64,
    /// Stale or invalid observations.
    pub errors: u64,
}

/// Explicit caller-driven reaper authority.
pub struct ProcessReaper {
    groups: Arc<ProcessGroupBook>,
}

impl ProcessReaper {
    /// Attach a reaper to one group book without starting a thread.
    pub fn new(groups: Arc<ProcessGroupBook>) -> Self {
        Self { groups }
    }

    /// Return the owned group book for adapter inspection.
    pub fn groups(&self) -> Arc<ProcessGroupBook> {
        Arc::clone(&self.groups)
    }

    /// Request group termination through the group authority.
    pub fn request_stop(
        &self,
        group: ProcessGroupId,
        reason: impl Into<String>,
    ) -> Result<ProcessGroupTerminationPlan, ProcessGroupError> {
        self.groups.begin_termination(group, reason)
    }

    /// Observe and reap a bounded number of members without blocking.
    pub fn sweep(
        &self,
        budget: ReaperBudget,
        mut observe: impl FnMut(ProcessHandle) -> ReaperObservation,
    ) -> ReaperReport {
        let plans = self.groups.draining_plans(budget.max_groups);
        let mut report = ReaperReport {
            groups_inspected: plans.len() as u64,
            ..ReaperReport::default()
        };
        let mut remaining = budget.max_members;
        for plan in plans {
            for raw in &plan.handles {
                if remaining == 0 {
                    return report;
                }
                remaining -= 1;
                report.members_inspected = report.members_inspected.saturating_add(1);
                let Some(handle) = ProcessHandle::from_raw(*raw) else {
                    report.errors = report.errors.saturating_add(1);
                    continue;
                };
                match observe(handle) {
                    ReaperObservation::Pending => {
                        report.pending = report.pending.saturating_add(1);
                    }
                    ReaperObservation::Unavailable => {
                        report.unavailable = report.unavailable.saturating_add(1);
                    }
                    ReaperObservation::Terminal(outcome) => {
                        match self.groups.mark_terminal(
                            plan_id(&plan),
                            plan.generation,
                            handle,
                            outcome,
                        ) {
                            Ok(_) => match self.groups.reap_member(plan_id(&plan), handle) {
                                Ok(_) => report.reaped = report.reaped.saturating_add(1),
                                Err(_) => report.errors = report.errors.saturating_add(1),
                            },
                            Err(_) => report.errors = report.errors.saturating_add(1),
                        }
                    }
                }
            }
        }
        report
    }
}

fn validate_name(name: &str) -> Result<(), ProcessGroupError> {
    if name.is_empty() || name.len() > PROCESS_GROUP_MAX_NAME_BYTES || name.contains('\0') {
        Err(ProcessGroupError::InvalidInput("name"))
    } else {
        Ok(())
    }
}

fn bounded_reason(reason: String) -> String {
    reason.chars().take(PROCESS_GROUP_MAX_NAME_BYTES).collect()
}

fn next_group_id(state: &mut GroupBookState) -> Result<ProcessGroupId, ProcessGroupError> {
    let id = ProcessGroupId::new(state.next_id).ok_or(ProcessGroupError::Capacity)?;
    state.next_id = state
        .next_id
        .checked_add(1)
        .ok_or(ProcessGroupError::Capacity)?;
    Ok(id)
}

fn terminal_state(outcome: MemberTerminal) -> GroupMemberState {
    match outcome {
        MemberTerminal::Exited(returncode) => GroupMemberState::Exited { returncode },
        MemberTerminal::Failed(reason) => GroupMemberState::Failed {
            reason: bounded_reason(reason),
        },
        MemberTerminal::Cancelled(reason) => GroupMemberState::Cancelled {
            reason: bounded_reason(reason),
        },
    }
}

fn snapshot(group: &ProcessGroupRecord) -> ProcessGroupSnapshot {
    ProcessGroupSnapshot {
        contract_version: PROCESS_GROUP_CONTRACT_VERSION,
        group_id: group.id.raw(),
        name: group.name.clone(),
        member_limit: group.member_limit,
        state: group.state,
        leader: group.leader.map(ProcessHandle::raw),
        generation: group.generation,
        reason: group.reason.clone(),
        members: group
            .members
            .values()
            .map(|member| ProcessGroupMember {
                handle: member.handle.raw(),
                state: member.state.clone(),
            })
            .collect(),
    }
}

fn termination_plan(group: &ProcessGroupRecord) -> ProcessGroupTerminationPlan {
    ProcessGroupTerminationPlan {
        contract_version: PROCESS_GROUP_CONTRACT_VERSION,
        group_id: group.id.raw(),
        generation: group.generation,
        reason: group.reason.clone(),
        handles: group.members.keys().copied().collect(),
    }
}

fn plan_id(plan: &ProcessGroupTerminationPlan) -> ProcessGroupId {
    ProcessGroupId::new(plan.group_id).expect("plans only contain valid group ids")
}
