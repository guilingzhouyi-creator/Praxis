//! Independent fixed-work benchmark-runner tests.

use l1_kernel_rs::benchmark::FixedWorkSpec;
use l1_kernel_rs::benchmark_runner::{
    run_agent_loop, run_agent_loop_batch, run_agent_loop_book_snapshot_page,
    run_agent_loop_registry_lookup, run_managed_process, run_process_adapter, run_process_bridge,
    run_process_group, run_queue_contention, run_queue_contention_blocking, run_registry_base,
    run_session_book, run_session_book_batch, run_session_book_snapshot_page,
    run_session_book_snapshot_page_write_contention, run_terminal_book, run_terminal_book_batch,
    run_terminal_book_snapshot_page, run_worker_pool_batch, run_worker_pool_batch_submit,
};

#[test]
fn queue_contention_runner_preserves_fixed_work_and_completeness() {
    let spec =
        FixedWorkSpec::new("substrate.queue.contention", 32, vec![1, 2], 1).expect("valid spec");
    let report = run_queue_contention(spec, 2).expect("runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 32
            && sample.p99_latency_ns >= sample.p95_latency_ns
            && sample.errors == 0
    }));
}

#[test]
fn process_bridge_runner_preserves_fixed_work_and_joint_reap() {
    let spec =
        FixedWorkSpec::new("process.bridge.lifecycle", 8, vec![1, 2], 1).expect("valid spec");
    let report = run_process_bridge(spec).expect("runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 8
            && sample.errors == 0
            && sample.rejected == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn process_group_runner_preserves_fixed_work_and_reaps_all_members() {
    let spec = FixedWorkSpec::new("process.group.reaper", 129, vec![1, 2], 1).expect("valid spec");
    let report = run_process_group(spec).expect("process-group runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 129
            && sample.rejected == 0
            && sample.errors == 0
            && sample.queue_wait_ns == 0
            && sample.lock_wait_ns == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn process_group_runner_rejects_more_workers_than_fixed_work() {
    let spec = FixedWorkSpec::new("process.group.reaper", 1, vec![2], 1).expect("valid spec");
    assert!(run_process_group(spec).is_err());
}

#[test]
fn queue_contention_runner_rejects_zero_capacity() {
    let spec = FixedWorkSpec::new("substrate.queue.contention", 4, vec![1], 1).expect("valid spec");
    assert!(run_queue_contention(spec, 0).is_err());
}

#[test]
fn blocking_contention_preserves_fixed_work_without_rejections() {
    let spec =
        FixedWorkSpec::new("substrate.queue.contention", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_queue_contention_blocking(spec, 2).expect("runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64 && sample.rejected == 0 && sample.errors == 0
    }));
}

#[test]
fn worker_pool_runner_preserves_fixed_work_and_reports_admission_tail() {
    let spec = FixedWorkSpec::new("worker.pool.batch", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_worker_pool_batch(spec, 64).expect("worker pool runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.queue_wait_ns > 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn worker_pool_runner_rejects_capacity_that_could_evict_fixed_work() {
    let spec = FixedWorkSpec::new("worker.pool.batch", 64, vec![1], 1).expect("valid spec");
    assert!(run_worker_pool_batch(spec, 63).is_err());
}

#[test]
fn worker_pool_batch_submit_runner_preserves_fixed_work_and_reports_batches() {
    let spec =
        FixedWorkSpec::new("worker.pool.batch_submit", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_worker_pool_batch_submit(spec, 64, 8).expect("batch-submit runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.queue_wait_ns > 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn worker_pool_batch_submit_runner_rejects_invalid_batch_size() {
    let spec = FixedWorkSpec::new("worker.pool.batch_submit", 4, vec![1], 1).expect("valid spec");
    assert!(run_worker_pool_batch_submit(spec.clone(), 4, 0).is_err());
    assert!(run_worker_pool_batch_submit(spec, 3, 2).is_err());
}

#[test]
fn session_book_runner_preserves_fixed_work_and_reports_tail_latency() {
    let spec = FixedWorkSpec::new("session.book.admission", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_session_book(spec, 4).expect("session runner succeeds");
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn session_book_runner_rejects_zero_shards() {
    let spec = FixedWorkSpec::new("session.book.admission", 4, vec![1], 1).expect("valid spec");
    assert!(run_session_book(spec, 0).is_err());
}

#[test]
fn session_snapshot_page_runner_preserves_fixed_page_requests() {
    let spec =
        FixedWorkSpec::new("session.book.snapshot_page", 32, vec![1, 2], 1).expect("valid spec");
    let report =
        run_session_book_snapshot_page(spec, 4, 64, 8).expect("snapshot page runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 32
            && sample.rejected == 0
            && sample.errors == 0
            && sample.queue_wait_ns == 0
            && sample.lock_wait_ns == 0
    }));
}

#[test]
fn session_snapshot_page_runner_rejects_invalid_read_boundary() {
    let spec = FixedWorkSpec::new("session.book.snapshot_page", 4, vec![1], 1).expect("valid spec");
    assert!(run_session_book_snapshot_page(spec.clone(), 0, 8, 2).is_err());
    assert!(run_session_book_snapshot_page(spec.clone(), 2, 2, 2).is_err());
    assert!(run_session_book_snapshot_page(spec, 2, 8, 0).is_err());
}

#[test]
fn agent_loop_snapshot_page_runner_preserves_fixed_page_requests() {
    let spec =
        FixedWorkSpec::new("agent_loop.book.snapshot_page", 16, vec![1, 2], 1).expect("valid spec");
    let report = run_agent_loop_book_snapshot_page(spec, 64, 8)
        .expect("agent loop snapshot page runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 16
            && sample.rejected == 0
            && sample.errors == 0
            && sample.queue_wait_ns == 0
            && sample.lock_wait_ns == 0
    }));
}

#[test]
fn terminal_snapshot_page_runner_preserves_fixed_page_requests() {
    let spec =
        FixedWorkSpec::new("terminal.book.snapshot_page", 16, vec![1, 2], 1).expect("valid spec");
    let report = run_terminal_book_snapshot_page(spec, 64, 8)
        .expect("terminal snapshot page runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 16
            && sample.rejected == 0
            && sample.errors == 0
            && sample.queue_wait_ns == 0
            && sample.lock_wait_ns == 0
    }));
}

#[test]
fn session_snapshot_page_write_contention_runner_preserves_fixed_bundles() {
    let spec = FixedWorkSpec::new(
        "session.book.snapshot_page_write_contention",
        32,
        vec![1, 2],
        1,
    )
    .expect("valid spec");
    let report = run_session_book_snapshot_page_write_contention(spec, 1, 64, 8)
        .expect("snapshot page contention runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 32
            && sample.rejected == 0
            && sample.errors == 0
            && sample.queue_wait_ns == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn session_snapshot_page_write_contention_rejects_invalid_boundary() {
    let spec = FixedWorkSpec::new("session.book.snapshot_page_write_contention", 4, vec![1], 1)
        .expect("valid spec");
    assert!(run_session_book_snapshot_page_write_contention(spec.clone(), 0, 8, 2).is_err());
    assert!(run_session_book_snapshot_page_write_contention(spec.clone(), 1, 2, 2).is_err());
    assert!(run_session_book_snapshot_page_write_contention(spec, 1, 8, 0).is_err());
}

#[test]
fn registry_base_runner_preserves_fixed_work_and_lookup_tail() {
    let spec = FixedWorkSpec::new("registry.base.lookup", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_registry_base(spec).expect("registry runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn session_book_batch_runner_preserves_fixed_work_and_reports_batch_tail() {
    let spec =
        FixedWorkSpec::new("session.book.batch_admission", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_session_book_batch(spec, 4, 8).expect("session batch runner succeeds");
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn session_book_batch_runner_rejects_zero_batch_size() {
    let spec =
        FixedWorkSpec::new("session.book.batch_admission", 4, vec![1], 1).expect("valid spec");
    assert!(run_session_book_batch(spec, 4, 0).is_err());
}

#[test]
fn agent_loop_runner_preserves_fixed_work_and_reports_lock_wait() {
    let spec = FixedWorkSpec::new("agent.loop.routing", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_agent_loop(spec).expect("agent loop runner succeeds");
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn agent_loop_runner_rejects_history_overflow() {
    let spec = FixedWorkSpec::new("agent.loop.routing", 16_385, vec![1], 1).expect("valid spec");
    assert!(run_agent_loop(spec).is_err());
}

#[test]
fn agent_loop_cached_handle_and_registry_lookup_reports_are_separate_and_complete() {
    let cached_spec =
        FixedWorkSpec::new("agent.loop.routing.cached", 32, vec![1, 2], 1).expect("valid spec");
    let baseline_spec =
        FixedWorkSpec::new("agent.loop.routing.lookup", 32, vec![1, 2], 1).expect("valid spec");
    let cached = run_agent_loop(cached_spec).expect("cached runner succeeds");
    let baseline = run_agent_loop_registry_lookup(baseline_spec).expect("lookup runner succeeds");
    assert!(cached.validate_complete().is_ok());
    assert!(baseline.validate_complete().is_ok());
    assert!(
        cached
            .samples
            .iter()
            .chain(baseline.samples.iter())
            .all(|sample| sample.completed_work_items == 32 && sample.errors == 0)
    );
}

#[test]
fn agent_loop_batch_runner_preserves_fixed_work_and_reports_batch_tail() {
    let spec =
        FixedWorkSpec::new("agent.loop.batch_admission", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_agent_loop_batch(spec, 8).expect("agent loop batch runner succeeds");
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn agent_loop_batch_runner_rejects_invalid_batch_size() {
    let spec = FixedWorkSpec::new("agent.loop.batch_admission", 4, vec![1], 1).expect("valid spec");
    assert!(run_agent_loop_batch(spec, 0).is_err());
}

#[test]
fn process_adapter_runner_preserves_fixed_work_and_reports_execution_errors() {
    let spec = FixedWorkSpec::new("process.adapter.oneshot", 8, vec![1, 2], 1).expect("valid spec");
    let report = run_process_adapter(spec).expect("process adapter runner succeeds");
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 8
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn managed_process_runner_preserves_fixed_work_and_reaps_handles() {
    let spec =
        FixedWorkSpec::new("process.managed.lifecycle", 16, vec![1, 2], 1).expect("valid spec");
    let report = run_managed_process(spec).expect("managed runner succeeds");
    assert!(report.validate_complete().is_ok());
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 16
            && sample.errors == 0
            && sample.rejected == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn terminal_book_runner_preserves_fixed_work() {
    let spec = FixedWorkSpec::new("terminal.book.mailbox", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_terminal_book(spec, 8).expect("terminal runner succeeds");
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
}

#[test]
fn terminal_book_batch_runner_preserves_fixed_work_and_validates_capacity() {
    let spec =
        FixedWorkSpec::new("terminal.book.batch_mailbox", 64, vec![1, 2], 1).expect("valid spec");
    let report = run_terminal_book_batch(spec.clone(), 8, 4).expect("terminal batch succeeds");
    assert_eq!(report.samples.len(), 2);
    assert!(report.samples.iter().all(|sample| {
        sample.completed_work_items == 64
            && sample.rejected == 0
            && sample.errors == 0
            && sample.p99_latency_ns >= sample.p95_latency_ns
    }));
    assert!(run_terminal_book_batch(spec.clone(), 8, 0).is_err());
    assert!(run_terminal_book_batch(spec, 4, 8).is_err());
}
