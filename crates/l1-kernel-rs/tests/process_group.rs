//! Independent tests for process-group ownership and bounded reaper planning.

use std::collections::BTreeMap;
use std::sync::Arc;

use l1_kernel_rs::process_group::{
    GroupMemberState, MemberTerminal, ProcessGroupBook, ProcessGroupError, ProcessGroupId,
    ProcessGroupState, ProcessReaper, ReaperBudget, ReaperObservation,
};
use l1_kernel_rs::substrate::ProcessHandle;

fn handle(slot: u32, generation: u32) -> ProcessHandle {
    ProcessHandle::new(slot, generation).expect("valid handle")
}

fn book() -> Arc<ProcessGroupBook> {
    Arc::new(ProcessGroupBook::new(4, 4).expect("group book"))
}

#[test]
fn constructor_and_value_limits_fail_closed() {
    assert_eq!(ProcessGroupId::new(0), None);
    assert!(matches!(
        ProcessGroupBook::new(0, 1),
        Err(ProcessGroupError::InvalidInput("max_groups"))
    ));
    assert!(matches!(
        ProcessGroupBook::new(1, 0),
        Err(ProcessGroupError::InvalidInput("max_members"))
    ));
    assert!(matches!(
        ProcessGroupBook::new(1, 4097),
        Err(ProcessGroupError::InvalidInput("max_members"))
    ));
    let groups = book();
    let invalid = "x".repeat(129);
    assert!(matches!(
        groups.create(invalid, None, None),
        Err(ProcessGroupError::InvalidInput("name"))
    ));
    assert!(matches!(
        groups.create("bounded", None, Some(0)),
        Err(ProcessGroupError::InvalidInput("member_limit"))
    ));
}

#[test]
fn leader_and_membership_are_unique_and_bounded() {
    let groups = book();
    let leader = handle(1, 1);
    let group = groups
        .create("agent-group", Some(leader), Some(2))
        .expect("create");
    assert_eq!(groups.group_for_handle(leader), Some(group));
    let second = handle(2, 1);
    groups.join(group, second).expect("join");
    assert_eq!(
        groups.join(group, handle(3, 1)),
        Err(ProcessGroupError::Capacity)
    );
    assert_eq!(
        groups.join(group, leader),
        Err(ProcessGroupError::HandleAlreadyGrouped)
    );
    let other = groups.create("other", None, None).expect("other");
    assert_eq!(
        groups.join(other, second),
        Err(ProcessGroupError::HandleAlreadyGrouped)
    );
    let snapshot = groups.snapshot(group).expect("snapshot");
    assert_eq!(snapshot.members.len(), 2);
    assert_eq!(snapshot.leader, Some(leader.raw()));
}

#[test]
fn leaving_active_group_releases_handle_and_leader() {
    let groups = book();
    let leader = handle(3, 2);
    let member = handle(4, 1);
    let group = groups.create("leave", Some(leader), None).expect("create");
    groups.join(group, member).expect("join");
    groups.leave(group, leader).expect("leader leave");
    assert_eq!(groups.group_for_handle(leader), None);
    assert_eq!(groups.snapshot(group).expect("snapshot").leader, None);
    groups.leave(group, member).expect("member leave");
    assert_eq!(groups.group_for_handle(member), None);
    assert_eq!(
        groups.leave(group, member),
        Err(ProcessGroupError::UnknownMember)
    );
}

#[test]
fn termination_plan_is_stable_and_blocks_new_members() {
    let groups = book();
    let first = handle(9, 1);
    let second = handle(7, 2);
    let group = groups.create("ordered", Some(first), None).expect("create");
    groups.join(group, second).expect("join");
    let plan = groups
        .begin_termination(group, "shutdown requested")
        .expect("terminate");
    assert_eq!(plan.group_id, group.raw());
    assert_eq!(plan.generation, 1);
    assert_eq!(plan.handles, vec![first.raw(), second.raw()]);
    assert_eq!(groups.termination_plan(group).expect("repeat"), plan);
    assert_eq!(
        groups.join(group, handle(11, 1)),
        Err(ProcessGroupError::InvalidState(ProcessGroupState::Draining))
    );
    let snapshot = groups.snapshot(group).expect("snapshot");
    assert_eq!(snapshot.state, ProcessGroupState::Draining);
    assert!(
        snapshot
            .members
            .iter()
            .all(|member| member.state == GroupMemberState::Stopping)
    );
}

#[test]
fn stale_and_duplicate_terminal_observations_fail_closed() {
    let groups = book();
    let process = handle(12, 4);
    let group = groups.create("stale", Some(process), None).expect("create");
    let plan = groups.begin_termination(group, "stop").expect("plan");
    assert_eq!(
        groups.mark_terminal(
            group,
            plan.generation + 1,
            process,
            MemberTerminal::Exited(1)
        ),
        Err(ProcessGroupError::StaleGeneration)
    );
    let stopped = groups
        .mark_terminal(group, plan.generation, process, MemberTerminal::Exited(0))
        .expect("terminal");
    assert_eq!(stopped.state, ProcessGroupState::Stopped);
    assert_eq!(
        groups.mark_terminal(group, plan.generation, process, MemberTerminal::Exited(0)),
        Err(ProcessGroupError::InvalidState(ProcessGroupState::Stopped))
    );
    let reaped = groups.reap_member(group, process).expect("reap");
    assert!(reaped.members.is_empty());
    assert_eq!(groups.group_for_handle(process), None);
}

#[test]
fn terminal_outcomes_are_bounded_and_snapshot_round_trips() {
    let groups = book();
    let failed = handle(20, 1);
    let cancelled = handle(21, 1);
    let group = groups
        .create("outcomes", Some(failed), None)
        .expect("create");
    groups.join(group, cancelled).expect("join");
    let plan = groups.begin_termination(group, "test").expect("plan");
    groups
        .mark_terminal(
            group,
            plan.generation,
            failed,
            MemberTerminal::Failed("adapter failed".to_owned()),
        )
        .expect("failed");
    let snapshot = groups
        .mark_terminal(
            group,
            plan.generation,
            cancelled,
            MemberTerminal::Cancelled("user stop".to_owned()),
        )
        .expect("cancelled");
    assert_eq!(snapshot.state, ProcessGroupState::Stopped);
    let encoded = serde_json::to_string(&snapshot).expect("encode");
    let decoded: l1_kernel_rs::process_group::ProcessGroupSnapshot =
        serde_json::from_str(&encoded).expect("decode");
    assert_eq!(decoded, snapshot);
    assert!(
        snapshot
            .members
            .iter()
            .any(|member| matches!(member.state, GroupMemberState::Failed { .. }))
    );
}

#[test]
fn reaper_sweep_is_fixed_work_and_reaps_terminal_members() {
    let groups = book();
    let first = handle(30, 1);
    let second = handle(31, 1);
    let third = handle(32, 1);
    let group = groups.create("reaper", Some(first), None).expect("create");
    groups.join(group, second).expect("join second");
    groups.join(group, third).expect("join third");
    let reaper = ProcessReaper::new(Arc::clone(&groups));
    reaper.request_stop(group, "bounded sweep").expect("stop");
    let mut seen = BTreeMap::new();
    let report = reaper.sweep(ReaperBudget::new(1, 2).expect("budget"), |process| {
        seen.insert(process.raw(), true);
        if process == second {
            ReaperObservation::Pending
        } else {
            ReaperObservation::Terminal(MemberTerminal::Exited(0))
        }
    });
    assert_eq!(report.groups_inspected, 1);
    assert_eq!(report.members_inspected, 2);
    assert_eq!(report.pending, 1);
    assert_eq!(report.reaped, 1);
    assert_eq!(seen.len(), 2);
    let remaining = groups.snapshot(group).expect("remaining");
    assert_eq!(remaining.members.len(), 2);
    assert_eq!(remaining.state, ProcessGroupState::Draining);
}

#[test]
fn reaper_handles_unavailable_and_invalid_budget_without_blocking() {
    let groups = book();
    let process = handle(40, 1);
    let group = groups
        .create("unavailable", Some(process), None)
        .expect("create");
    let reaper = ProcessReaper::new(Arc::clone(&groups));
    reaper.request_stop(group, "owner lost").expect("stop");
    let report = reaper.sweep(ReaperBudget::new(1, 1).expect("budget"), |_| {
        ReaperObservation::Unavailable
    });
    assert_eq!(report.unavailable, 1);
    assert_eq!(report.reaped, 0);
    assert_eq!(
        ReaperBudget::new(0, 1),
        Err(ProcessGroupError::InvalidInput("reaper_budget"))
    );
    assert_eq!(
        ReaperBudget::new(1, 0),
        Err(ProcessGroupError::InvalidInput("reaper_budget"))
    );
}

#[test]
fn reaper_can_finish_multiple_groups_in_stable_order() {
    let groups = book();
    let first = handle(50, 1);
    let second = handle(51, 1);
    let one = groups.create("one", Some(first), None).expect("one");
    let two = groups.create("two", Some(second), None).expect("two");
    let reaper = ProcessReaper::new(Arc::clone(&groups));
    reaper.request_stop(two, "second").expect("stop two");
    reaper.request_stop(one, "first").expect("stop one");
    let mut order = Vec::new();
    let report = reaper.sweep(ReaperBudget::new(2, 2).expect("budget"), |process| {
        order.push(process.slot());
        ReaperObservation::Terminal(MemberTerminal::Exited(0))
    });
    assert_eq!(report.groups_inspected, 2);
    assert_eq!(report.reaped, 2);
    assert_eq!(order, vec![first.slot(), second.slot()]);
    assert_eq!(groups.snapshot(one).expect("one").members.len(), 0);
    assert_eq!(groups.snapshot(two).expect("two").members.len(), 0);
}

#[test]
fn failed_groups_reject_new_stop_plans_but_keep_diagnostics() {
    let groups = book();
    let process = handle(60, 3);
    let group = groups
        .create("failed", Some(process), None)
        .expect("create");
    let snapshot = groups.fail(group, "ownership mismatch").expect("fail");
    assert_eq!(snapshot.state, ProcessGroupState::Failed);
    assert_eq!(snapshot.reason, "ownership mismatch");
    assert_eq!(
        groups.begin_termination(group, "again"),
        Err(ProcessGroupError::InvalidState(ProcessGroupState::Failed))
    );
    assert_eq!(groups.group_for_handle(process), Some(group));
}
