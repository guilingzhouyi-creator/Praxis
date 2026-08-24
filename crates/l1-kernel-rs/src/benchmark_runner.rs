//! Run a Rust-native fixed-work queue contention candidate.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use crate::agent_loop::{AgentLoopBook, AgentLoopSpec};
use crate::benchmark::{BenchmarkReport, BenchmarkResources, BenchmarkSample, FixedWorkSpec};
use crate::managed_process::{ManagedProcessBook, ManagedWaitResult};
use crate::process::{ProcessTable, ProcessTableConfig};
use crate::process_adapter::{ProcessAdapter, ProcessAdapterConfig};
use crate::process_bridge::ProcessTableBridge;
use crate::process_group::{
    MemberTerminal, ProcessGroupBook, ProcessReaper, ReaperBudget, ReaperObservation,
};
use crate::registry_base::{MapRegistry, RegisterableSpec};
use crate::session::{SESSION_MAX_MESSAGES, SessionBook, SessionInput, SessionSpec};
use crate::snapshot::BOOK_SNAPSHOT_MAX_PAGE_SIZE;
use crate::state_queue::{BoundedWorkQueue, WorkItem};
use crate::substrate::{ProcessHandle, QueueMetrics};
use crate::terminal::{TerminalBook, TerminalSpec};
use crate::worker::{TaskFn, WorkerConfig, WorkerPool};
use serde_json::Value;

const P95_PERCENT: usize = 95;
const P99_PERCENT: usize = 99;
const PERCENT_DENOMINATOR: usize = 100;
const CONSUMER_BATCH_SIZE: usize = 32;
const WORKER_POOL_IDLE_TIMEOUT_MS: u64 = 100;
const PROCESS_BENCH_TIMEOUT_MS: u64 = 2_000;
const MANAGED_PROCESS_BENCH_TIMEOUT_MS: u64 = 2_000;
const PROCESS_GROUP_SWEEP_MEMBER_BUDGET: usize = 64;

type SnapshotPageReader<B> = dyn Fn(&B) -> Result<u64, &'static str> + Send + Sync;

#[derive(Debug, Clone, Copy, Default)]
struct ResourceSnapshot {
    cpu_time_ns: Option<u64>,
    memory_bytes: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum QueueMode {
    Reject,
    Blocking,
}

/// Run a fixed-total multi-producer queue contention sweep.
///
/// Admission duration is reported as queue-admission lock/backpressure wait;
/// it is intentionally not presented as an isolated mutex benchmark.
pub fn run_queue_contention(
    spec: FixedWorkSpec,
    queue_capacity: usize,
) -> Result<BenchmarkReport, &'static str> {
    run_queue_contention_mode(spec, queue_capacity, QueueMode::Reject)
}

/// Run the same fixed-work sweep with condition-variable backpressure.
///
/// This path keeps accepted work bounded without producer busy-spinning. It is
/// an optimization candidate only; callers still choose whether a fail-fast
/// rejection policy or a blocking admission policy belongs in production.
pub fn run_queue_contention_blocking(
    spec: FixedWorkSpec,
    queue_capacity: usize,
) -> Result<BenchmarkReport, &'static str> {
    run_queue_contention_mode(spec, queue_capacity, QueueMode::Blocking)
}

/// Run a fixed-total WorkerPool batch sweep.
///
/// This runner measures the public WorkerPool admission and batch completion
/// boundary, not the lower-level `state_queue` contention path. Queue capacity
/// must cover the fixed batch so eviction cannot turn the measurement into a
/// backpressure policy experiment.
pub fn run_worker_pool_batch(
    spec: FixedWorkSpec,
    queue_capacity: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if queue_capacity == 0 {
        return Err("worker pool queue capacity must be positive");
    }
    if queue_capacity < total_work {
        return Err("worker pool queue capacity must cover fixed work");
    }

    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_worker_pool_round(
                total_work,
                worker_count,
                round,
                queue_capacity,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run the fixed-work WorkerPool sweep with grouped task admission.
///
/// This is a separate evidence workload from [`run_worker_pool_batch`]. It
/// measures the public batch-submission boundary so the admission-lock
/// optimization can be compared with the per-task baseline without mixing
/// their latency distributions. Queue capacity must still cover all work.
pub fn run_worker_pool_batch_submit(
    spec: FixedWorkSpec,
    queue_capacity: usize,
    submit_batch_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if queue_capacity == 0 {
        return Err("worker pool queue capacity must be positive");
    }
    if queue_capacity < total_work {
        return Err("worker pool queue capacity must cover fixed work");
    }
    if submit_batch_size == 0 {
        return Err("worker pool submit batch size must be positive");
    }

    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_worker_pool_batch_submit_round(
                total_work,
                worker_count,
                round,
                queue_capacity,
                submit_batch_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total session-admission sweep across a sharded `SessionBook`.
///
/// Each work item creates, activates, and appends one independent session.
/// The workload measures the Rust-native identity/history hot path; it does
/// not invoke AgentLoop, providers, tools, terminals, or persistence.
pub fn run_session_book(
    spec: FixedWorkSpec,
    shard_count: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if shard_count == 0 {
        return Err("session book shard count must be positive");
    }
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_session_book_round(
                total_work,
                worker_count,
                round,
                shard_count,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run the grouped session-admission candidate with one lock per shard batch.
///
/// Batch latency is reported as its own distribution, separate from
/// [`run_session_book`]'s per-session operation latency. Queue and lock waits
/// remain zero because the session book has no queue boundary or wait probe.
pub fn run_session_book_batch(
    spec: FixedWorkSpec,
    shard_count: usize,
    submit_batch_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if shard_count == 0 {
        return Err("session book shard count must be positive");
    }
    if submit_batch_size == 0 {
        return Err("session book batch size must be positive");
    }
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_session_book_batch_round(
                total_work,
                worker_count,
                round,
                shard_count,
                submit_batch_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total bounded SessionBook snapshot-page sweep.
///
/// Each work item reads one identity-ordered page from an already populated
/// sharded registry. Registry construction is deliberately outside the timed
/// interval so page-request latency is not conflated with session admission or
/// durable checkpoint export. The returned work unit is one page request.
pub fn run_session_book_snapshot_page(
    spec: FixedWorkSpec,
    shard_count: usize,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "snapshot page work does not fit the target architecture")?;
    validate_session_book_snapshot_page_config(shard_count, registry_entries, page_size)?;

    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_session_book_snapshot_page_round(
                total_work,
                worker_count,
                round,
                shard_count,
                registry_entries,
                page_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run fixed page-read and session-write bundles against one shared book.
///
/// A work item first verifies the leading page and then admits one unique
/// session. It measures cross-mode registry contention without turning either
/// public operation into a timed production API. The reported latency covers
/// the complete bundle, while `lock_wait_ns` sums only blocked read/write lock
/// fallbacks. This is evidence for the session mechanism only, not a writer
/// fairness or runtime-routing policy.
pub fn run_session_book_snapshot_page_write_contention(
    spec: FixedWorkSpec,
    shard_count: usize,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "snapshot page write contention work does not fit the target architecture")?;
    validate_session_book_snapshot_page_config(shard_count, registry_entries, page_size)?;

    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_session_book_snapshot_page_write_contention_round(
                total_work,
                worker_count,
                round,
                shard_count,
                registry_entries,
                page_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total bounded AgentLoopBook snapshot-page sweep.
///
/// Loop identities are seeded outside the timed interval. This workload only
/// measures the registry page read boundary; it does not attach sessions,
/// terminals, or start logical execution.
pub fn run_agent_loop_book_snapshot_page(
    spec: FixedWorkSpec,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "agent loop snapshot page work does not fit the target architecture")?;
    validate_registry_snapshot_page_config(registry_entries, page_size)?;
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_agent_loop_book_snapshot_page_round(
                total_work,
                worker_count,
                round,
                registry_entries,
                page_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total bounded TerminalBook snapshot-page sweep.
///
/// Terminal records are seeded outside the timed interval. Mailbox and
/// process-binding operations stay outside this registry read workload.
pub fn run_terminal_book_snapshot_page(
    spec: FixedWorkSpec,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "terminal snapshot page work does not fit the target architecture")?;
    validate_registry_snapshot_page_config(registry_entries, page_size)?;
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_terminal_book_snapshot_page_round(
                total_work,
                worker_count,
                round,
                registry_entries,
                page_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total declarative registry registration and lookup sweep.
///
/// Each item registers a unique descriptor and immediately resolves it again.
/// Registration order remains an observable output invariant, while the
/// internal name lookup is measured through the Rust-native hash index.
pub fn run_registry_base(spec: FixedWorkSpec) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "registry work does not fit the target architecture")?;
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_registry_base_round(total_work, worker_count, round)?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total logical AgentLoop input-admission sweep.
///
/// One loop/session/terminal identity is shared by the worker sweep so the
/// workload measures the serialized routing boundary. Session history remains
/// the authoritative message truth; terminal mailbox mutation and provider or
/// tool execution are intentionally excluded.
pub fn run_agent_loop(spec: FixedWorkSpec) -> Result<BenchmarkReport, &'static str> {
    run_agent_loop_mode(spec, true)
}

/// Run the registry-lookup AgentLoop baseline for comparison.
///
/// This intentionally resolves the loop identity through `AgentLoopBook` for
/// every item. It is kept as a separate workload so cached-handle evidence does
/// not get compared against a different operation unit.
pub fn run_agent_loop_registry_lookup(
    spec: FixedWorkSpec,
) -> Result<BenchmarkReport, &'static str> {
    run_agent_loop_mode(spec, false)
}

/// Run a fixed-total grouped logical AgentLoop input-admission sweep.
///
/// The fixed work count is identical to [`run_agent_loop`], but latency
/// samples represent one batch rather than one input. The workload is kept
/// separate so per-item and per-batch tail values are never compared as if
/// they had the same unit.
pub fn run_agent_loop_batch(
    spec: FixedWorkSpec,
    batch_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if total_work > SESSION_MAX_MESSAGES {
        return Err("agent loop workload exceeds session history bound");
    }
    if batch_size == 0 {
        return Err("agent loop batch size must be positive");
    }
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_agent_loop_batch_round(
                total_work,
                worker_count,
                round,
                batch_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

fn run_agent_loop_mode(
    spec: FixedWorkSpec,
    cached_handle: bool,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if total_work > SESSION_MAX_MESSAGES {
        return Err("agent loop workload exceeds session history bound");
    }
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_agent_loop_round(
                total_work,
                worker_count,
                round,
                cached_handle,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total bounded one-shot ProcessPort sweep.
///
/// Each item starts one short-lived direct-argument shell process. The runner
/// measures the Rust adapter boundary only; it does not register a process in
/// `ProcessTable`, attach a PTY, or grant execution authority to runtime code.
pub fn run_process_adapter(spec: FixedWorkSpec) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_process_adapter_round(total_work, worker_count, round)?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total managed-process lifecycle sweep.
///
/// Each item owns one direct-argument child through spawn, wait, and reap. The
/// report measures handle ownership and lifecycle overhead separately from the
/// one-shot adapter workload; it does not attach a PTY or invoke policy.
pub fn run_managed_process(spec: FixedWorkSpec) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    let max_processes =
        u32::try_from(total_work).map_err(|_| "managed process capacity is too large")?;
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_managed_process_round(
                total_work,
                worker_count,
                round,
                max_processes,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total ProcessTable-registered managed-process lifecycle sweep.
///
/// This keeps the ProcessTable bridge overhead separate from the managed-child
/// baseline. The public handle is the table handle, and every item must pass
/// through spawn, wait, and joint reap before it counts as completed.
pub fn run_process_bridge(spec: FixedWorkSpec) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    let max_processes =
        u32::try_from(total_work).map_err(|_| "bridge process capacity is too large")?;
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_process_bridge_round(
                total_work,
                worker_count,
                round,
                max_processes,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run a fixed-total caller-owned process-group reaper sweep.
///
/// Each worker owns an independent group so the fixed-work report measures
/// group-member terminal admission and reaping under the requested worker
/// count. No OS child, PTY, process-group signal, or background reaper is
/// involved; this is a mechanism-only lock/contention workload.
pub fn run_process_group(spec: FixedWorkSpec) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "process-group work does not fit the target architecture")?;
    if total_work == 0 {
        return Err("process-group work must be positive");
    }
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count =
            usize::try_from(workers).map_err(|_| "process-group worker count is not supported")?;
        if worker_count == 0 || worker_count > total_work {
            return Err("process-group worker count must not exceed fixed work");
        }
        for round in 0..spec.rounds {
            report.push(run_process_group_round(total_work, worker_count, round)?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

fn run_process_group_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
) -> Result<BenchmarkSample, &'static str> {
    let base = total_work / worker_count;
    let remainder = total_work % worker_count;
    let mut workers = Vec::with_capacity(worker_count);
    for worker in 0..worker_count {
        let member_count = base + usize::from(worker < remainder);
        let groups = Arc::new(
            ProcessGroupBook::new(1, member_count)
                .map_err(|_| "process-group book creation failed")?,
        );
        let group = groups
            .create(
                format!("bench-process-group-{round:02}-{worker:02}"),
                None,
                None,
            )
            .map_err(|_| "process-group creation failed")?;
        for slot in 0..member_count {
            let handle = ProcessHandle::new((slot + 1) as u32, 1)
                .ok_or("process-group benchmark handle creation failed")?;
            groups
                .join(group, handle)
                .map_err(|_| "process-group member admission failed")?;
        }
        let reaper = ProcessReaper::new(groups);
        reaper
            .request_stop(group, "fixed-work benchmark")
            .map_err(|_| "process-group stop planning failed")?;
        workers.push((reaper, group, member_count));
    }

    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut threads = Vec::with_capacity(worker_count);
    for (reaper, group, member_count) in workers {
        threads.push(thread::spawn(move || {
            let operation_started = Instant::now();
            let mut reaped = 0_u64;
            while reaped < member_count as u64 {
                let remaining = member_count as u64 - reaped;
                let member_budget =
                    remaining.min(PROCESS_GROUP_SWEEP_MEMBER_BUDGET as u64) as usize;
                let report = reaper.sweep(
                    ReaperBudget::new(1, member_budget)
                        .map_err(|_| "process-group benchmark budget is invalid")?,
                    |_handle| ReaperObservation::Terminal(MemberTerminal::Exited(0)),
                );
                if report.groups_inspected != 1
                    || report.pending != 0
                    || report.unavailable != 0
                    || report.errors != 0
                    || report.reaped == 0
                {
                    return Err("process-group benchmark did not preserve bounded progress");
                }
                reaped = reaped.saturating_add(report.reaped);
            }
            if reaped != member_count as u64 {
                return Err("process-group benchmark did not preserve fixed work");
            }
            let _ = group;
            Ok::<_, &'static str>(operation_started.elapsed().as_nanos().max(1) as u64)
        }));
    }

    let mut latencies = Vec::with_capacity(worker_count);
    for thread in threads {
        latencies.push(
            thread
                .join()
                .map_err(|_| "process-group benchmark worker panicked")??,
        );
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_managed_process_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    max_processes: u32,
) -> Result<BenchmarkSample, &'static str> {
    let book = Arc::new(
        ManagedProcessBook::new(ProcessAdapterConfig::standard(), max_processes)
            .map_err(|_| "managed process book creation failed")?,
    );
    let args = Arc::new(process_benchmark_args());
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);
    for _ in 0..worker_count {
        let book = Arc::clone(&book);
        let args = Arc::clone(&args);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            let mut errors = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                match book.spawn_args(args.as_ref(), None) {
                    Ok(handle) => {
                        match book.wait(
                            handle,
                            Duration::from_millis(MANAGED_PROCESS_BENCH_TIMEOUT_MS),
                        ) {
                            Ok(ManagedWaitResult::Finished(result)) if result.ok() => {}
                            Ok(ManagedWaitResult::Finished(_)) => errors = errors.saturating_add(1),
                            Ok(ManagedWaitResult::Pending) => {
                                errors = errors.saturating_add(1);
                                let _ = book.terminate(handle, Duration::from_secs(1));
                            }
                            Err(_) => errors = errors.saturating_add(1),
                        }
                        if book.reap(handle).is_err() {
                            errors = errors.saturating_add(1);
                        }
                    }
                    Err(_) => errors = errors.saturating_add(1),
                }
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>((latencies, errors))
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    let mut errors = 0_u64;
    for worker in workers {
        let (worker_latencies, worker_errors) = worker
            .join()
            .map_err(|_| "managed process benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        errors = errors.saturating_add(worker_errors);
    }
    if latencies.len() != total_work || book.active_count() != 0 {
        return Err("managed process benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_process_bridge_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    max_processes: u32,
) -> Result<BenchmarkSample, &'static str> {
    let table = Arc::new(ProcessTable::new(ProcessTableConfig::new(
        total_work.saturating_mul(2).saturating_add(1),
        "kernel",
        "init",
        3,
        1,
    )));
    let bridge = Arc::new(
        ProcessTableBridge::new(
            ProcessAdapterConfig::standard(),
            max_processes,
            Arc::clone(&table),
        )
        .map_err(|_| "process bridge creation failed")?,
    );
    let args = Arc::new(process_benchmark_args());
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);
    for _ in 0..worker_count {
        let bridge = Arc::clone(&bridge);
        let args = Arc::clone(&args);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            let mut errors = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                match bridge.spawn_args(args.as_ref(), None) {
                    Ok(handle) => {
                        match bridge.wait(
                            handle,
                            Duration::from_millis(MANAGED_PROCESS_BENCH_TIMEOUT_MS),
                        ) {
                            Ok(ManagedWaitResult::Finished(result)) if result.ok() => {}
                            Ok(ManagedWaitResult::Finished(_)) => errors = errors.saturating_add(1),
                            Ok(ManagedWaitResult::Pending) => {
                                errors = errors.saturating_add(1);
                                let _ = bridge.terminate(handle, Duration::from_secs(1));
                            }
                            Err(_) => errors = errors.saturating_add(1),
                        }
                        if bridge.reap(handle).is_err() {
                            errors = errors.saturating_add(1);
                        }
                    }
                    Err(_) => errors = errors.saturating_add(1),
                }
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>((latencies, errors))
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    let mut errors = 0_u64;
    for worker in workers {
        let (worker_latencies, worker_errors) = worker
            .join()
            .map_err(|_| "process bridge benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        errors = errors.saturating_add(worker_errors);
    }
    if latencies.len() != total_work
        || bridge.active_count() != 0
        || table.list_processes(None).len() != 1
    {
        return Err("process bridge benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_process_adapter_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
) -> Result<BenchmarkSample, &'static str> {
    let adapter = Arc::new(ProcessAdapter::default());
    let args = Arc::new(process_benchmark_args());
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);
    for _ in 0..worker_count {
        let adapter = Arc::clone(&adapter);
        let args = Arc::clone(&args);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            let mut errors = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                let result = adapter.run_args(
                    args.as_ref(),
                    Duration::from_millis(PROCESS_BENCH_TIMEOUT_MS),
                    None,
                );
                if !result.ok() {
                    errors = errors.saturating_add(1);
                }
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>((latencies, errors))
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    let mut errors = 0_u64;
    for worker in workers {
        let (worker_latencies, worker_errors) = worker
            .join()
            .map_err(|_| "process adapter benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        errors = errors.saturating_add(worker_errors);
    }
    if latencies.len() != total_work {
        return Err("process adapter benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn process_benchmark_args() -> Vec<String> {
    #[cfg(unix)]
    {
        vec![
            "/bin/sh".to_owned(),
            "-c".to_owned(),
            "printf process-benchmark".to_owned(),
        ]
    }
    #[cfg(windows)]
    {
        vec![
            "cmd.exe".to_owned(),
            "/C".to_owned(),
            "echo process-benchmark".to_owned(),
        ]
    }
}

/// Run a fixed-total per-frame terminal mailbox sweep.
///
/// Each work item submits and consumes one frame through a shared
/// `TerminalBook`. Terminal registration and lifecycle setup are included in
/// the measured round so the baseline and grouped candidate have identical
/// ownership costs. PTY, subprocess, and AgentLoop work remain out of scope.
pub fn run_terminal_book(
    spec: FixedWorkSpec,
    frame_capacity: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if frame_capacity == 0 {
        return Err("terminal frame capacity must be positive");
    }
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_terminal_book_round(
                total_work,
                worker_count,
                round,
                frame_capacity,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

/// Run the grouped terminal mailbox candidate with one registry lock per
/// input/output batch.
pub fn run_terminal_book_batch(
    spec: FixedWorkSpec,
    frame_capacity: usize,
    submit_batch_size: usize,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if frame_capacity == 0 {
        return Err("terminal frame capacity must be positive");
    }
    if submit_batch_size == 0 || submit_batch_size > frame_capacity {
        return Err("terminal submit batch size must fit frame capacity");
    }
    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            report.push(run_terminal_book_batch_round(
                total_work,
                worker_count,
                round,
                frame_capacity,
                submit_batch_size,
            )?)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

fn run_queue_contention_mode(
    spec: FixedWorkSpec,
    queue_capacity: usize,
    mode: QueueMode,
) -> Result<BenchmarkReport, &'static str> {
    let total_work = usize::try_from(spec.total_work_items)
        .map_err(|_| "total work does not fit the target architecture")?;
    if total_work > u32::MAX as usize {
        return Err("total work exceeds process handle slot range");
    }

    let mut report = BenchmarkReport::new(spec.clone());
    for &workers in &spec.workers {
        let worker_count = usize::try_from(workers).map_err(|_| "worker count is not supported")?;
        for round in 0..spec.rounds {
            let sample = run_round(total_work, worker_count, round, queue_capacity, mode)?;
            report.push(sample)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

fn run_terminal_book_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    frame_capacity: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book = Arc::new(TerminalBook::new());
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for worker in 0..worker_count {
        let book = Arc::clone(&book);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let terminal_id = format!("bench-terminal-{round:02}-{worker:02}");
            let session_id = format!("bench-terminal-session-{round:02}-{worker:02}");
            let process = ProcessHandle::new(worker as u32 + 1, round + 1)
                .ok_or("terminal benchmark process handle is invalid")?;
            book.register(TerminalSpec::new(
                terminal_id.clone(),
                frame_capacity,
                frame_capacity,
            ))
            .map_err(|_| "terminal registration failed")?;
            book.attach(&terminal_id, session_id)
                .map_err(|_| "terminal session attach failed")?;
            book.bind_process_handle(&terminal_id, process)
                .map_err(|_| "terminal process bind failed")?;
            book.start(&terminal_id)
                .map_err(|_| "terminal start failed")?;

            let mut latencies = Vec::with_capacity(total_work);
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                book.submit_input(&terminal_id, work_index.to_string().into_bytes())
                    .map_err(|_| "terminal input submission failed")?;
                let frame = book
                    .take_input(&terminal_id)
                    .map_err(|_| "terminal input consumption failed")?
                    .ok_or("terminal input frame was lost")?;
                if frame.data != work_index.to_string().as_bytes() {
                    return Err("terminal input payload changed");
                }
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            book.stop(&terminal_id)
                .map_err(|_| "terminal stop failed")?;
            book.close(&terminal_id)
                .map_err(|_| "terminal close failed")?;
            Ok::<_, &'static str>(latencies)
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    for worker in workers {
        latencies.extend(
            worker
                .join()
                .map_err(|_| "terminal benchmark worker panicked")??,
        );
    }
    if latencies.len() != total_work {
        return Err("terminal benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_terminal_book_batch_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    frame_capacity: usize,
    submit_batch_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book = Arc::new(TerminalBook::new());
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for worker in 0..worker_count {
        let book = Arc::clone(&book);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let terminal_id = format!("bench-terminal-batch-{round:02}-{worker:02}");
            let session_id = format!("bench-terminal-batch-session-{round:02}-{worker:02}");
            let process = ProcessHandle::new(worker as u32 + 1, round + 1)
                .ok_or("terminal batch benchmark process handle is invalid")?;
            book.register(TerminalSpec::new(
                terminal_id.clone(),
                frame_capacity,
                frame_capacity,
            ))
            .map_err(|_| "terminal batch registration failed")?;
            book.attach(&terminal_id, session_id)
                .map_err(|_| "terminal batch session attach failed")?;
            book.bind_process_handle(&terminal_id, process)
                .map_err(|_| "terminal batch process bind failed")?;
            book.start(&terminal_id)
                .map_err(|_| "terminal batch start failed")?;

            let mut latencies = Vec::new();
            let mut completed = 0_usize;
            loop {
                let start_index =
                    next_work.fetch_add(submit_batch_size as u64, Ordering::Relaxed) as usize;
                if start_index >= total_work {
                    break;
                }
                let count = (total_work - start_index).min(submit_batch_size);
                let payloads = (0..count)
                    .map(|offset| (start_index + offset).to_string().into_bytes())
                    .collect::<Vec<_>>();
                let operation_started = Instant::now();
                let results = book
                    .submit_input_batch(&terminal_id, payloads)
                    .map_err(|_| "terminal batch input submission failed")?;
                if results.len() != count || results.iter().any(Result::is_err) {
                    return Err("terminal batch input admission failed");
                }
                let frames = book
                    .take_input_batch(&terminal_id, count)
                    .map_err(|_| "terminal batch input consumption failed")?;
                if frames.len() != count {
                    return Err("terminal batch input frames were lost");
                }
                for (offset, frame) in frames.into_iter().enumerate() {
                    let expected = (start_index + offset).to_string().into_bytes();
                    if frame.data != expected {
                        return Err("terminal batch input payload changed");
                    }
                }
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
                completed += count;
            }
            book.stop(&terminal_id)
                .map_err(|_| "terminal batch stop failed")?;
            book.close(&terminal_id)
                .map_err(|_| "terminal batch close failed")?;
            Ok::<_, &'static str>((latencies, completed))
        }));
    }

    let mut latencies = Vec::new();
    let mut completed = 0_usize;
    for worker in workers {
        let (worker_latencies, worker_completed) = worker
            .join()
            .map_err(|_| "terminal batch benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        completed += worker_completed;
    }
    if completed != total_work || latencies.is_empty() {
        return Err("terminal batch benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: completed as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_session_book_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    shard_count: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book = Arc::new(SessionBook::new(shard_count).map_err(|_| "session book creation failed")?);
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for worker in 0..worker_count {
        let book = Arc::clone(&book);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            let mut lock_wait_ns = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                let session_id = format!("bench-{round:02}-{worker:02}-{work_index:08}");
                let (session, admission_lock_wait_ns) = book
                    .create_with_lock_wait(SessionSpec::new(
                        session_id.clone(),
                        "bench-agent",
                        "bench-cell",
                        "worker",
                        2,
                    ))
                    .map_err(|_| "session admission failed")?;
                lock_wait_ns = lock_wait_ns.saturating_add(admission_lock_wait_ns);
                session
                    .activate()
                    .map_err(|_| "session activation failed")?;
                session
                    .append_input(format!("{session_id}-input"), "payload", work_index as u64)
                    .map_err(|_| "session input admission failed")?;
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>((latencies, lock_wait_ns))
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    let mut lock_wait_ns = 0_u64;
    for worker in workers {
        let (worker_latencies, worker_lock_wait_ns) = worker
            .join()
            .map_err(|_| "session benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        lock_wait_ns = lock_wait_ns.saturating_add(worker_lock_wait_ns);
    }
    if latencies.len() != total_work {
        return Err("session benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_session_book_batch_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    shard_count: usize,
    submit_batch_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book = Arc::new(SessionBook::new(shard_count).map_err(|_| "session book creation failed")?);
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for worker in 0..worker_count {
        let book = Arc::clone(&book);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut batch_latencies = Vec::new();
            let mut completed = 0_usize;
            loop {
                let start_index =
                    next_work.fetch_add(submit_batch_size as u64, Ordering::Relaxed) as usize;
                if start_index >= total_work {
                    break;
                }
                let count = (total_work - start_index).min(submit_batch_size);
                let specs = (0..count)
                    .map(|offset| {
                        let index = start_index + offset;
                        SessionSpec::new(
                            format!("bench-batch-{round:02}-{worker:02}-{index:08}"),
                            "bench-agent",
                            "bench-cell",
                            "worker",
                            2,
                        )
                    })
                    .collect::<Vec<_>>();
                let admission_started = Instant::now();
                let sessions = book.create_batch(specs);
                batch_latencies.push(admission_started.elapsed().as_nanos().max(1) as u64);
                for (offset, result) in sessions.into_iter().enumerate() {
                    let session = result.map_err(|_| "session batch admission failed")?;
                    session
                        .activate()
                        .map_err(|_| "session batch activation failed")?;
                    let index = start_index + offset;
                    session
                        .append_input(
                            format!("bench-batch-input-{round:02}-{worker:02}-{index:08}"),
                            "payload",
                            index as u64,
                        )
                        .map_err(|_| "session batch input admission failed")?;
                }
                completed += count;
            }
            Ok::<_, &'static str>((batch_latencies, completed))
        }));
    }

    let mut batch_latencies = Vec::new();
    let mut completed = 0_usize;
    for worker in workers {
        let (latencies, worker_completed) = worker
            .join()
            .map_err(|_| "session batch benchmark worker panicked")??;
        batch_latencies.extend(latencies);
        completed += worker_completed;
    }
    if completed != total_work || batch_latencies.is_empty() {
        return Err("session batch benchmark did not preserve fixed work");
    }
    batch_latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: completed as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&batch_latencies, P95_PERCENT),
        p99_latency_ns: percentile(&batch_latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_session_book_snapshot_page_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    shard_count: usize,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book =
        Arc::new(SessionBook::new(shard_count).map_err(|_| "snapshot page book creation failed")?);
    let first_session_id = format!("snapshot-page-{round:02}-{:08}", 0);
    let last_page_session_id = format!("snapshot-page-{round:02}-{:08}", page_size - 1);
    for entry in 0..registry_entries {
        book.create(SessionSpec::new(
            format!("snapshot-page-{round:02}-{entry:08}"),
            "bench-agent",
            "bench-cell",
            "worker",
            1,
        ))
        .map_err(|_| "snapshot page seed session admission failed")?;
    }

    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for _ in 0..worker_count {
        let book = Arc::clone(&book);
        let next_work = Arc::clone(&next_work);
        let first_session_id = first_session_id.clone();
        let last_page_session_id = last_page_session_id.clone();
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            let mut lock_wait_ns = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                let (page, page_lock_wait_ns) = book
                    .snapshot_page_with_lock_wait(None, page_size)
                    .map_err(|_| "snapshot page request failed")?;
                lock_wait_ns = lock_wait_ns.saturating_add(page_lock_wait_ns);
                if page.items.len() != page_size
                    || page.next_cursor.is_none()
                    || page
                        .items
                        .first()
                        .is_none_or(|snapshot| snapshot.spec.session_id != first_session_id)
                    || page
                        .items
                        .last()
                        .is_none_or(|snapshot| snapshot.spec.session_id != last_page_session_id)
                {
                    return Err("snapshot page result did not preserve bounded identity order");
                }
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>((latencies, lock_wait_ns))
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    let mut lock_wait_ns = 0_u64;
    for worker in workers {
        let (worker_latencies, worker_lock_wait_ns) = worker
            .join()
            .map_err(|_| "snapshot page benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        lock_wait_ns = lock_wait_ns.saturating_add(worker_lock_wait_ns);
    }
    if latencies.len() != total_work {
        return Err("snapshot page benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_agent_loop_book_snapshot_page_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book = Arc::new(AgentLoopBook::new());
    let first_loop_id = format!("snapshot-page-{round:02}-{:08}", 0);
    let last_page_loop_id = format!("snapshot-page-{round:02}-{:08}", page_size - 1);
    for entry in 0..registry_entries {
        book.register(AgentLoopSpec::new(
            format!("snapshot-page-{round:02}-{entry:08}"),
            "bench-agent",
            "bench-cell",
            "bench-session",
            "bench-terminal",
        ))
        .map_err(|_| "agent loop snapshot page seed admission failed")?;
    }
    let first_loop_id_for_reader = first_loop_id.clone();
    let last_page_loop_id_for_reader = last_page_loop_id.clone();
    let reader = Arc::new(move |book: &AgentLoopBook| {
        let (page, lock_wait_ns) = book
            .snapshot_page_with_lock_wait(None, page_size)
            .map_err(|_| "agent loop snapshot page request failed")?;
        if page.items.len() != page_size
            || page.next_cursor.is_none()
            || page
                .items
                .first()
                .is_none_or(|snapshot| snapshot.spec.loop_id != first_loop_id_for_reader)
            || page
                .items
                .last()
                .is_none_or(|snapshot| snapshot.spec.loop_id != last_page_loop_id_for_reader)
        {
            return Err("agent loop snapshot page order changed");
        }
        Ok(lock_wait_ns)
    });
    run_snapshot_page_round(book, total_work, worker_count, round, reader)
}

fn run_terminal_book_snapshot_page_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book = Arc::new(TerminalBook::new());
    let first_terminal_id = format!("snapshot-page-{round:02}-{:08}", 0);
    let last_page_terminal_id = format!("snapshot-page-{round:02}-{:08}", page_size - 1);
    for entry in 0..registry_entries {
        book.register(TerminalSpec::new(
            format!("snapshot-page-{round:02}-{entry:08}"),
            1,
            1,
        ))
        .map_err(|_| "terminal snapshot page seed admission failed")?;
    }
    let first_terminal_id_for_reader = first_terminal_id.clone();
    let last_page_terminal_id_for_reader = last_page_terminal_id.clone();
    let reader = Arc::new(move |book: &TerminalBook| {
        let (page, lock_wait_ns) = book
            .snapshot_page_with_lock_wait(None, page_size)
            .map_err(|_| "terminal snapshot page request failed")?;
        if page.items.len() != page_size
            || page.next_cursor.is_none()
            || page
                .items
                .first()
                .is_none_or(|snapshot| snapshot.terminal_id != first_terminal_id_for_reader)
            || page
                .items
                .last()
                .is_none_or(|snapshot| snapshot.terminal_id != last_page_terminal_id_for_reader)
        {
            return Err("terminal snapshot page order changed");
        }
        Ok(lock_wait_ns)
    });
    run_snapshot_page_round(book, total_work, worker_count, round, reader)
}

fn run_snapshot_page_round<B>(
    book: Arc<B>,
    total_work: usize,
    worker_count: usize,
    round: u32,
    reader: Arc<SnapshotPageReader<B>>,
) -> Result<BenchmarkSample, &'static str>
where
    B: Send + Sync + 'static,
{
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);
    for _ in 0..worker_count {
        let book = Arc::clone(&book);
        let next_work = Arc::clone(&next_work);
        let reader = Arc::clone(&reader);
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            let mut lock_wait_ns = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                lock_wait_ns = lock_wait_ns.saturating_add(reader(&book)?);
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>((latencies, lock_wait_ns))
        }));
    }
    let mut latencies = Vec::with_capacity(total_work);
    let mut lock_wait_ns = 0_u64;
    for worker in workers {
        let (worker_latencies, worker_lock_wait_ns) = worker
            .join()
            .map_err(|_| "snapshot page benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        lock_wait_ns = lock_wait_ns.saturating_add(worker_lock_wait_ns);
    }
    if latencies.len() != total_work {
        return Err("snapshot page benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_session_book_snapshot_page_write_contention_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    shard_count: usize,
    registry_entries: usize,
    page_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let book =
        Arc::new(SessionBook::new(shard_count).map_err(|_| "snapshot page book creation failed")?);
    let first_session_id = format!("snapshot-page-{round:02}-{:08}", 0);
    let last_page_session_id = format!("snapshot-page-{round:02}-{:08}", page_size - 1);
    for entry in 0..registry_entries {
        book.create(SessionSpec::new(
            format!("snapshot-page-{round:02}-{entry:08}"),
            "bench-agent",
            "bench-cell",
            "worker",
            1,
        ))
        .map_err(|_| "snapshot page contention seed session admission failed")?;
    }

    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for _ in 0..worker_count {
        let book = Arc::clone(&book);
        let next_work = Arc::clone(&next_work);
        let first_session_id = first_session_id.clone();
        let last_page_session_id = last_page_session_id.clone();
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            let mut lock_wait_ns = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                let (page, page_lock_wait_ns) = book
                    .snapshot_page_with_lock_wait(None, page_size)
                    .map_err(|_| "snapshot page contention request failed")?;
                lock_wait_ns = lock_wait_ns.saturating_add(page_lock_wait_ns);
                if page.items.len() != page_size
                    || page.next_cursor.is_none()
                    || page
                        .items
                        .first()
                        .is_none_or(|snapshot| snapshot.spec.session_id != first_session_id)
                    || page
                        .items
                        .last()
                        .is_none_or(|snapshot| snapshot.spec.session_id != last_page_session_id)
                {
                    return Err("snapshot page contention changed leading page order");
                }
                let (_, write_lock_wait_ns) = book
                    .create_with_lock_wait(SessionSpec::new(
                        format!("snapshot-page-zwrite-{round:02}-{work_index:08}"),
                        "bench-agent",
                        "bench-cell",
                        "worker",
                        1,
                    ))
                    .map_err(|_| "snapshot page contention write admission failed")?;
                lock_wait_ns = lock_wait_ns.saturating_add(write_lock_wait_ns);
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>((latencies, lock_wait_ns))
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    let mut lock_wait_ns = 0_u64;
    for worker in workers {
        let (worker_latencies, worker_lock_wait_ns) = worker
            .join()
            .map_err(|_| "snapshot page contention benchmark worker panicked")??;
        latencies.extend(worker_latencies);
        lock_wait_ns = lock_wait_ns.saturating_add(worker_lock_wait_ns);
    }
    if latencies.len() != total_work {
        return Err("snapshot page contention benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn validate_session_book_snapshot_page_config(
    shard_count: usize,
    registry_entries: usize,
    page_size: usize,
) -> Result<(), &'static str> {
    if shard_count == 0 {
        return Err("snapshot page shard count must be positive");
    }
    validate_registry_snapshot_page_config(registry_entries, page_size)
}

fn validate_registry_snapshot_page_config(
    registry_entries: usize,
    page_size: usize,
) -> Result<(), &'static str> {
    if page_size == 0 || page_size > BOOK_SNAPSHOT_MAX_PAGE_SIZE {
        return Err("snapshot page size is outside the public bound");
    }
    if registry_entries <= page_size {
        return Err("snapshot page registry must contain a following record");
    }
    Ok(())
}

fn run_registry_base_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
) -> Result<BenchmarkSample, &'static str> {
    let registry = Arc::new(MapRegistry::new(false));
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for worker in 0..worker_count {
        let registry = Arc::clone(&registry);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                let name = format!("bench-registry-{round:02}-{worker:02}-{work_index:08}");
                let mut spec = RegisterableSpec::new(name.clone());
                spec.category = if work_index.is_multiple_of(2) {
                    "even".to_owned()
                } else {
                    "odd".to_owned()
                };
                if !registry.register(spec, "fixed-work benchmark") {
                    return Err("registry benchmark registration was rejected");
                }
                if registry.get(&name).is_none() {
                    return Err("registry benchmark lookup missed a registered item");
                }
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>(latencies)
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    for worker in workers {
        latencies.extend(
            worker
                .join()
                .map_err(|_| "registry benchmark worker panicked")??,
        );
    }
    let stats = registry.stats();
    if latencies.len() != total_work || stats.total != total_work || stats.registers != total_work {
        return Err("registry benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: 0,
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_agent_loop_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    cached_handle: bool,
) -> Result<BenchmarkSample, &'static str> {
    let sessions = Arc::new(SessionBook::new(1).map_err(|_| "agent loop session book failed")?);
    let session = sessions
        .create(SessionSpec::new(
            format!("bench-agent-loop-session-{round:02}"),
            "bench-agent",
            "bench-cell",
            "worker",
            total_work,
        ))
        .map_err(|_| "agent loop session admission failed")?;
    session
        .activate()
        .map_err(|_| "agent loop session activation failed")?;
    let terminals = TerminalBook::new();
    terminals
        .register(TerminalSpec::new(
            format!("bench-agent-loop-terminal-{round:02}"),
            1,
            1,
        ))
        .map_err(|_| "agent loop terminal registration failed")?;
    terminals
        .attach(
            &format!("bench-agent-loop-terminal-{round:02}"),
            session.id(),
        )
        .map_err(|_| "agent loop terminal attachment failed")?;
    let loops = Arc::new(AgentLoopBook::new());
    let loop_id = format!("bench-agent-loop-{round:02}");
    let terminal_id = format!("bench-agent-loop-terminal-{round:02}");
    loops
        .register(AgentLoopSpec::new(
            loop_id.clone(),
            "bench-agent",
            "bench-cell",
            session.id(),
            terminal_id,
        ))
        .map_err(|_| "agent loop registration failed")?;
    loops
        .attach(&loop_id, &session, &terminals)
        .map_err(|_| "agent loop correlation failed")?;
    loops
        .start(&loop_id)
        .map_err(|_| "agent loop start failed")?;
    let cached_loop = if cached_handle {
        Some(
            loops
                .handle(&loop_id)
                .map_err(|_| "agent loop handle lookup failed")?,
        )
    } else {
        None
    };
    let baseline_lock_wait_ns = loops
        .snapshot(&loop_id)
        .map_err(|_| "agent loop baseline snapshot failed")?
        .lock_wait_ns;

    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);
    for _ in 0..worker_count {
        let loops = Arc::clone(&loops);
        let session = Arc::clone(&session);
        let next_work = Arc::clone(&next_work);
        let loop_id = loop_id.clone();
        let cached_loop = cached_loop.clone();
        workers.push(thread::spawn(move || {
            let mut latencies = Vec::new();
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let operation_started = Instant::now();
                let result = match &cached_loop {
                    Some(handle) => handle.admit_input(
                        &session,
                        format!("bench-agent-loop-input-{work_index:08}"),
                        "payload",
                        work_index as u64,
                    ),
                    None => loops.admit_input(
                        &loop_id,
                        &session,
                        format!("bench-agent-loop-input-{work_index:08}"),
                        "payload",
                        work_index as u64,
                    ),
                };
                result.map_err(|_| "agent loop input admission failed")?;
                latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
            }
            Ok::<_, &'static str>(latencies)
        }));
    }

    let mut latencies = Vec::with_capacity(total_work);
    for worker in workers {
        latencies.extend(
            worker
                .join()
                .map_err(|_| "agent loop benchmark worker panicked")??,
        );
    }
    if latencies.len() != total_work || session.message_count() != total_work {
        return Err("agent loop benchmark did not preserve fixed work");
    }
    latencies.sort_unstable();
    let snapshot = loops
        .snapshot(&loop_id)
        .map_err(|_| "agent loop final snapshot failed")?;
    if snapshot.accepted_commands != total_work as u64 || snapshot.failed_commands != 0 {
        return Err("agent loop benchmark reported admission errors");
    }
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&latencies, P95_PERCENT),
        p99_latency_ns: percentile(&latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: snapshot.lock_wait_ns.saturating_sub(baseline_lock_wait_ns),
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_agent_loop_batch_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    batch_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let sessions = Arc::new(SessionBook::new(1).map_err(|_| "agent loop session book failed")?);
    let session = sessions
        .create(SessionSpec::new(
            format!("bench-agent-loop-batch-session-{round:02}"),
            "bench-agent",
            "bench-cell",
            "worker",
            total_work,
        ))
        .map_err(|_| "agent loop batch session admission failed")?;
    session
        .activate()
        .map_err(|_| "agent loop batch session activation failed")?;
    let terminals = TerminalBook::new();
    let terminal_id = format!("bench-agent-loop-batch-terminal-{round:02}");
    terminals
        .register(TerminalSpec::new(terminal_id.clone(), 1, 1))
        .map_err(|_| "agent loop batch terminal registration failed")?;
    terminals
        .attach(&terminal_id, session.id())
        .map_err(|_| "agent loop batch terminal attachment failed")?;
    let loops = Arc::new(AgentLoopBook::new());
    let loop_id = format!("bench-agent-loop-batch-{round:02}");
    loops
        .register(AgentLoopSpec::new(
            loop_id.clone(),
            "bench-agent",
            "bench-cell",
            session.id(),
            terminal_id,
        ))
        .map_err(|_| "agent loop batch registration failed")?;
    loops
        .attach(&loop_id, &session, &terminals)
        .map_err(|_| "agent loop batch correlation failed")?;
    loops
        .start(&loop_id)
        .map_err(|_| "agent loop batch start failed")?;
    let handle = loops
        .handle(&loop_id)
        .map_err(|_| "agent loop batch handle lookup failed")?;
    let baseline_lock_wait_ns = handle.snapshot().lock_wait_ns;

    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);
    for worker in 0..worker_count {
        let handle = handle.clone();
        let session = Arc::clone(&session);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut batch_latencies = Vec::new();
            let mut completed = 0_usize;
            loop {
                let start_index =
                    next_work.fetch_add(batch_size as u64, Ordering::Relaxed) as usize;
                if start_index >= total_work {
                    break;
                }
                let count = (total_work - start_index).min(batch_size);
                let inputs = (0..count)
                    .map(|offset| {
                        let index = start_index + offset;
                        SessionInput::new(
                            format!(
                                "bench-agent-loop-batch-input-{round:02}-{worker:02}-{index:08}"
                            ),
                            "payload",
                            index as u64,
                        )
                    })
                    .collect::<Vec<_>>();
                let operation_started = Instant::now();
                let results = handle.admit_input_batch(&session, inputs);
                for result in results {
                    result.map_err(|_| "agent loop batch input admission failed")?;
                }
                batch_latencies.push(operation_started.elapsed().as_nanos().max(1) as u64);
                completed += count;
            }
            Ok::<_, &'static str>((batch_latencies, completed))
        }));
    }

    let mut batch_latencies = Vec::new();
    let mut completed = 0_usize;
    for worker in workers {
        let (latencies, worker_completed) = worker
            .join()
            .map_err(|_| "agent loop batch benchmark worker panicked")??;
        batch_latencies.extend(latencies);
        completed += worker_completed;
    }
    if completed != total_work || session.message_count() != total_work {
        return Err("agent loop batch benchmark did not preserve fixed work");
    }
    batch_latencies.sort_unstable();
    let snapshot = handle.snapshot();
    if snapshot.accepted_commands != total_work as u64 || snapshot.failed_commands != 0 {
        return Err("agent loop batch benchmark reported admission errors");
    }
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: total_work as u64,
        elapsed_ns,
        p95_latency_ns: percentile(&batch_latencies, P95_PERCENT),
        p99_latency_ns: percentile(&batch_latencies, P99_PERCENT),
        queue_wait_ns: 0,
        lock_wait_ns: snapshot.lock_wait_ns.saturating_sub(baseline_lock_wait_ns),
        rejected: 0,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    queue_capacity: usize,
    mode: QueueMode,
) -> Result<BenchmarkSample, &'static str> {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = Arc::new(BoundedWorkQueue::new(queue_capacity, Arc::clone(&metrics))?);
    let next_work = Arc::new(AtomicU64::new(0));
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut workers = Vec::with_capacity(worker_count);

    for _ in 0..worker_count {
        let queue = Arc::clone(&queue);
        let next_work = Arc::clone(&next_work);
        workers.push(thread::spawn(move || {
            let mut admission_latencies = Vec::new();
            let mut lock_wait_ns = 0_u64;
            loop {
                let work_index = next_work.fetch_add(1, Ordering::Relaxed) as usize;
                if work_index >= total_work {
                    break;
                }
                let handle = ProcessHandle::new(work_index as u32, 1)
                    .ok_or("benchmark process handle could not be created")?;
                let admission_started = Instant::now();
                let item = WorkItem {
                    handle,
                    sequence: work_index as u64,
                };
                match mode {
                    QueueMode::Reject => {
                        while !queue.try_push(item) {
                            thread::yield_now();
                        }
                    }
                    QueueMode::Blocking => queue.push_wait(item),
                }
                let admission_ns = admission_started.elapsed().as_nanos().max(1) as u64;
                admission_latencies.push(admission_ns);
                lock_wait_ns = lock_wait_ns.saturating_add(admission_ns);
            }
            Ok::<_, &'static str>((admission_latencies, lock_wait_ns))
        }));
    }

    let mut completed = 0_usize;
    let mut queue_wait_ns = 0_u64;
    let mut batch = Vec::with_capacity(CONSUMER_BATCH_SIZE);
    while completed < total_work {
        let pop_started = Instant::now();
        match mode {
            QueueMode::Reject => {
                batch.clear();
                let drained = queue.drain_batch(CONSUMER_BATCH_SIZE, &mut batch);
                if drained > 0 {
                    queue.record_complete_batch(drained);
                    completed += drained;
                } else {
                    queue_wait_ns =
                        queue_wait_ns.saturating_add(pop_started.elapsed().as_nanos() as u64);
                    thread::yield_now();
                }
            }
            QueueMode::Blocking => {
                let _item = queue.pop_wait();
                queue_wait_ns =
                    queue_wait_ns.saturating_add(pop_started.elapsed().as_nanos() as u64);
                queue.record_complete();
                completed += 1;
            }
        }
    }

    let mut admission_latencies = Vec::with_capacity(total_work);
    let mut lock_wait_ns = 0_u64;
    for worker in workers {
        let (latencies, worker_lock_wait_ns) =
            worker.join().map_err(|_| "benchmark worker panicked")??;
        admission_latencies.extend(latencies);
        lock_wait_ns = lock_wait_ns.saturating_add(worker_lock_wait_ns);
    }
    admission_latencies.sort_unstable();
    if admission_latencies.len() != total_work {
        return Err("benchmark admission count does not match fixed work");
    }

    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    let snapshot = metrics.snapshot();
    if snapshot.completed as usize != total_work || snapshot.queue_depth != 0 {
        return Err("benchmark queue did not drain completely");
    }
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: snapshot.completed,
        elapsed_ns,
        p95_latency_ns: percentile(&admission_latencies, P95_PERCENT),
        p99_latency_ns: percentile(&admission_latencies, P99_PERCENT),
        queue_wait_ns,
        lock_wait_ns,
        rejected: snapshot.rejected,
        errors: 0,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_worker_pool_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    queue_capacity: usize,
) -> Result<BenchmarkSample, &'static str> {
    let pool = WorkerPool::new(WorkerConfig::new(
        worker_count,
        worker_count,
        queue_capacity,
        std::time::Duration::from_millis(WORKER_POOL_IDLE_TIMEOUT_MS),
    ))?;
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut handles = Vec::with_capacity(total_work);
    let mut admission_latencies = Vec::with_capacity(total_work);
    let mut lock_wait_ns = 0_u64;
    for _ in 0..total_work {
        let admission_started = Instant::now();
        handles.push(pool.submit_result(Box::new(|| Ok(Value::Null))));
        let admission_ns = admission_started.elapsed().as_nanos().max(1) as u64;
        admission_latencies.push(admission_ns);
        lock_wait_ns = lock_wait_ns.saturating_add(admission_ns);
    }

    let mut errors = 0_u64;
    for handle in handles {
        if handle.result(None).is_err() {
            errors = errors.saturating_add(1);
        }
    }
    let shutdown = pool.shutdown(true, Some(std::time::Duration::from_secs(5)));
    if shutdown.get("success") != Some(&Value::Bool(true)) {
        return Err("worker pool benchmark did not shut down cleanly");
    }
    admission_latencies.sort_unstable();
    let snapshot = pool.stats();
    let completed = snapshot
        .get("completed")
        .and_then(Value::as_u64)
        .ok_or("worker pool benchmark completed metric is missing")?;
    let rejected = snapshot
        .get("rejected")
        .and_then(Value::as_u64)
        .ok_or("worker pool benchmark rejected metric is missing")?;
    let queue_wait_ns = snapshot
        .get("queue_wait_ns")
        .and_then(Value::as_u64)
        .ok_or("worker pool benchmark queue wait metric is missing")?;
    if completed != total_work as u64 || rejected != 0 {
        return Err("worker pool benchmark did not preserve fixed work");
    }
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: completed,
        elapsed_ns,
        p95_latency_ns: percentile(&admission_latencies, P95_PERCENT),
        p99_latency_ns: percentile(&admission_latencies, P99_PERCENT),
        queue_wait_ns,
        lock_wait_ns,
        rejected,
        errors,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn run_worker_pool_batch_submit_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    queue_capacity: usize,
    submit_batch_size: usize,
) -> Result<BenchmarkSample, &'static str> {
    let pool = WorkerPool::new(WorkerConfig::new(
        worker_count,
        worker_count,
        queue_capacity,
        std::time::Duration::from_millis(WORKER_POOL_IDLE_TIMEOUT_MS),
    ))?;
    let resources_before = resource_snapshot();
    let started = Instant::now();
    let mut handles = Vec::with_capacity(total_work);
    let mut admission_latencies = Vec::with_capacity(total_work.div_ceil(submit_batch_size));
    let mut lock_wait_ns = 0_u64;
    let mut submitted = 0_usize;
    while submitted < total_work {
        let count = (total_work - submitted).min(submit_batch_size);
        let actions = (0..count)
            .map(|_| Box::new(|| Ok(Value::Null)) as TaskFn)
            .collect::<Vec<_>>();
        let admission_started = Instant::now();
        handles.extend(pool.submit_result_batch(actions));
        let admission_ns = admission_started.elapsed().as_nanos().max(1) as u64;
        admission_latencies.push(admission_ns);
        lock_wait_ns = lock_wait_ns.saturating_add(admission_ns);
        submitted += count;
    }

    let mut errors = 0_u64;
    for handle in handles {
        if handle.result(None).is_err() {
            errors = errors.saturating_add(1);
        }
    }
    let shutdown = pool.shutdown(true, Some(std::time::Duration::from_secs(5)));
    if shutdown.get("success") != Some(&Value::Bool(true)) {
        return Err("worker pool batch-submit benchmark did not shut down cleanly");
    }
    admission_latencies.sort_unstable();
    let snapshot = pool.stats();
    let completed = snapshot
        .get("completed")
        .and_then(Value::as_u64)
        .ok_or("worker pool batch-submit completed metric is missing")?;
    let rejected = snapshot
        .get("rejected")
        .and_then(Value::as_u64)
        .ok_or("worker pool batch-submit rejected metric is missing")?;
    let queue_wait_ns = snapshot
        .get("queue_wait_ns")
        .and_then(Value::as_u64)
        .ok_or("worker pool batch-submit queue wait metric is missing")?;
    if completed != total_work as u64 || rejected != 0 {
        return Err("worker pool batch-submit benchmark did not preserve fixed work");
    }
    let elapsed_ns = started.elapsed().as_nanos().max(1) as u64;
    let resources_after = resource_snapshot();
    Ok(BenchmarkSample {
        workers: worker_count as u32,
        round,
        completed_work_items: completed,
        elapsed_ns,
        p95_latency_ns: percentile(&admission_latencies, P95_PERCENT),
        p99_latency_ns: percentile(&admission_latencies, P99_PERCENT),
        queue_wait_ns,
        lock_wait_ns,
        rejected,
        errors,
        resources: resource_delta(resources_before, resources_after),
    })
}

fn resource_snapshot() -> ResourceSnapshot {
    #[cfg(target_os = "linux")]
    {
        ResourceSnapshot {
            cpu_time_ns: read_procfs_cpu_time_ns(),
            memory_bytes: read_procfs_hwm_bytes(),
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        ResourceSnapshot::default()
    }
}

#[cfg(target_os = "linux")]
fn read_procfs_cpu_time_ns() -> Option<u64> {
    std::fs::read_to_string("/proc/self/schedstat")
        .ok()?
        .split_whitespace()
        .next()?
        .parse()
        .ok()
}

#[cfg(target_os = "linux")]
fn read_procfs_hwm_bytes() -> Option<u64> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    let line = status.lines().find(|line| line.starts_with("VmHWM:"))?;
    let kilobytes = line.split_whitespace().nth(1)?.parse::<u64>().ok()?;
    kilobytes.checked_mul(1024)
}

fn resource_delta(before: ResourceSnapshot, after: ResourceSnapshot) -> BenchmarkResources {
    let cpu_time_ns = before
        .cpu_time_ns
        .zip(after.cpu_time_ns)
        .map(|(start, end)| end.saturating_sub(start));
    let memory_bytes = before
        .memory_bytes
        .zip(after.memory_bytes)
        .map(|(start, end)| end.saturating_sub(start));
    BenchmarkResources {
        cpu_time_ns,
        memory_bytes,
        cpu_source: if cpu_time_ns.is_some() {
            "procfs.schedstat".to_owned()
        } else {
            "unavailable".to_owned()
        },
        memory_source: if memory_bytes.is_some() {
            "procfs.status.vm_hwm".to_owned()
        } else {
            "unavailable".to_owned()
        },
    }
}

fn percentile(sorted_values: &[u64], percentile: usize) -> u64 {
    let rank = (sorted_values.len() * percentile).div_ceil(PERCENT_DENOMINATOR);
    sorted_values[rank.saturating_sub(1)]
}
