//! Independent scheduler-candidate tests for the Rust kernel.

use l1_kernel_rs::scheduler::{KernelScheduler, SchedulerConfig, SchedulerError};
use l1_kernel_rs::state_queue::TaskState;

fn scheduler(queue_capacity: usize) -> KernelScheduler {
    KernelScheduler::new(SchedulerConfig::new(4, 2, queue_capacity)).expect("valid scheduler")
}

#[test]
fn scheduler_owns_spawn_schedule_claim_complete_lifecycle() {
    let scheduler = scheduler(2);
    let handle = scheduler.spawn().expect("spawn");
    assert_eq!(
        scheduler.state(handle).expect("state").state,
        TaskState::Ready
    );
    scheduler.schedule(handle, 7).expect("schedule");
    let item = scheduler.claim_next().expect("claim");
    assert_eq!(item.handle, handle);
    assert_eq!(item.sequence, 7);
    assert_eq!(
        scheduler.state(handle).expect("state").state,
        TaskState::Running
    );
    scheduler.complete(handle).expect("complete");
    assert_eq!(
        scheduler.state(handle).expect("state").state,
        TaskState::Ready
    );
    assert_eq!(scheduler.queue_metrics().completed, 1);
}

#[test]
fn scheduler_rolls_back_state_when_queue_is_full() {
    let scheduler = scheduler(1);
    let first = scheduler.spawn().expect("first");
    let second = scheduler.spawn().expect("second");
    scheduler.schedule(first, 1).expect("first schedule");
    assert_eq!(
        scheduler.schedule(second, 2),
        Err(SchedulerError::QueueFull)
    );
    assert_eq!(
        scheduler.state(second).expect("state").state,
        TaskState::Ready
    );
    assert_eq!(scheduler.claim_next().expect("claim").handle, first);
    scheduler.complete(first).expect("complete");
    scheduler.schedule(second, 3).expect("retry schedule");
}

#[test]
fn direct_dispatch_preserves_state_without_queue_accounting() {
    let scheduler = scheduler(2);
    let handle = scheduler.spawn().expect("spawn");
    scheduler.dispatch_direct(handle).expect("direct dispatch");
    assert_eq!(
        scheduler.state(handle).expect("state").state,
        TaskState::Running
    );
    assert_eq!(scheduler.queue_metrics().submitted, 0);
    scheduler.complete_direct(handle).expect("direct complete");
    assert_eq!(
        scheduler.state(handle).expect("state").state,
        TaskState::Ready
    );
    assert_eq!(scheduler.queue_metrics().completed, 0);
    scheduler.reap(handle).expect("reap");
}

#[test]
fn stopped_work_is_discarded_and_reaped_handles_fail_closed_after_reuse() {
    let scheduler = scheduler(2);
    let old = scheduler.spawn().expect("spawn");
    scheduler.schedule(old, 11).expect("schedule");
    scheduler.stop(old).expect("stop");
    assert!(scheduler.claim_next().is_none());
    assert_eq!(scheduler.queue_metrics().completed, 1);
    scheduler.reap(old).expect("reap");
    assert!(scheduler.state(old).is_none());

    let reused = scheduler.spawn().expect("reuse slot");
    assert_eq!(reused.slot(), old.slot());
    assert_ne!(reused.generation(), old.generation());
    assert_eq!(scheduler.stop(old), Err(SchedulerError::InvalidHandle));
}

#[test]
fn scheduler_rejects_running_reap_and_stale_completion() {
    let scheduler = scheduler(2);
    let handle = scheduler.spawn().expect("spawn");
    scheduler.schedule(handle, 1).expect("schedule");
    assert_eq!(scheduler.reap(handle), Err(SchedulerError::NotReapable));
    assert!(scheduler.claim_next().is_some());
    scheduler.complete(handle).expect("complete");
    scheduler.reap(handle).expect("reap");
    assert_eq!(
        scheduler.complete(handle),
        Err(SchedulerError::InvalidState)
    );
}
