//! Run a Rust-native fixed-work queue contention candidate.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::Instant;

use crate::benchmark::{BenchmarkReport, BenchmarkSample, FixedWorkSpec};
use crate::state_queue::{BoundedWorkQueue, WorkItem};
use crate::substrate::{ProcessHandle, QueueMetrics};

const P95_PERCENT: usize = 95;
const P99_PERCENT: usize = 99;
const PERCENT_DENOMINATOR: usize = 100;

/// Run a fixed-total multi-producer queue contention sweep.
///
/// Admission duration is reported as queue-admission lock/backpressure wait;
/// it is intentionally not presented as an isolated mutex benchmark.
pub fn run_queue_contention(
    spec: FixedWorkSpec,
    queue_capacity: usize,
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
            let sample = run_round(total_work, worker_count, round, queue_capacity)?;
            report.push(sample)?;
        }
    }
    report.validate_complete()?;
    Ok(report)
}

fn run_round(
    total_work: usize,
    worker_count: usize,
    round: u32,
    queue_capacity: usize,
) -> Result<BenchmarkSample, &'static str> {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = Arc::new(BoundedWorkQueue::new(queue_capacity, Arc::clone(&metrics))?);
    let next_work = Arc::new(AtomicU64::new(0));
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
                while !queue.try_push(WorkItem {
                    handle,
                    sequence: work_index as u64,
                }) {
                    thread::yield_now();
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
    while completed < total_work {
        let pop_started = Instant::now();
        if queue.try_pop().is_some() {
            queue.record_complete();
            completed += 1;
        } else {
            queue_wait_ns = queue_wait_ns.saturating_add(pop_started.elapsed().as_nanos() as u64);
            thread::yield_now();
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
    })
}

fn percentile(sorted_values: &[u64], percentile: usize) -> u64 {
    let rank = (sorted_values.len() * percentile).div_ceil(PERCENT_DENOMINATOR);
    sorted_values[rank.saturating_sub(1)]
}

#[cfg(test)]
mod tests {
    use super::run_queue_contention;
    use crate::benchmark::FixedWorkSpec;

    #[test]
    fn queue_contention_runner_preserves_fixed_work_and_completeness() {
        let spec = FixedWorkSpec::new("substrate.queue.contention", 32, vec![1, 2], 1)
            .expect("valid spec");
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
    fn queue_contention_runner_rejects_zero_capacity() {
        let spec =
            FixedWorkSpec::new("substrate.queue.contention", 4, vec![1], 1).expect("valid spec");
        assert!(run_queue_contention(spec, 0).is_err());
    }
}
