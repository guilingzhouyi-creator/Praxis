//! Independent substrate-value and metric tests for the Rust kernel.

use l1_kernel_rs::substrate::{ProcessHandle, QueueMetrics, ShardPlan};

#[test]
fn generation_tagged_handles_round_trip_and_reject_zero() {
    assert!(ProcessHandle::new(7, 0).is_none());
    let handle = ProcessHandle::new(7, 3).expect("valid handle");
    assert_eq!(ProcessHandle::from_raw(handle.raw()), Some(handle));
    assert_eq!(handle.slot(), 7);
    assert_eq!(handle.generation(), 3);
    assert!(ProcessHandle::from_raw(7).is_none());
}

#[test]
fn shard_plan_is_deterministic_and_rejects_empty_layout() {
    assert!(ShardPlan::new(0).is_err());
    let plan = ShardPlan::new(4).expect("valid plan");
    let handle = ProcessHandle::new(9, 1).expect("valid handle");
    assert_eq!(plan.shard_count(), 4);
    assert_eq!(plan.shard_for(handle), 1);
}

#[test]
fn queue_metrics_track_admission_completion_and_peak() {
    let metrics = QueueMetrics::new();
    metrics.record_submit(true);
    metrics.record_submit(true);
    metrics.record_submit(false);
    metrics.record_complete();
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.submitted, 2);
    assert_eq!(snapshot.completed, 1);
    assert_eq!(snapshot.rejected, 1);
    assert_eq!(snapshot.queue_depth, 1);
    assert_eq!(snapshot.peak_queue_depth, 2);
}

#[test]
fn duplicate_completion_does_not_underflow_depth() {
    let metrics = QueueMetrics::new();
    metrics.record_complete();
    metrics.record_complete();
    assert_eq!(metrics.snapshot().queue_depth, 0);
    assert_eq!(metrics.snapshot().completed, 2);
}
