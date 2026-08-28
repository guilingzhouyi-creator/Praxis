//! Public integration coverage for worker cancellation and deadlines.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use l1_kernel_rs::worker::{TaskHandleError, WorkerConfig, WorkerPool};
use serde_json::json;

#[test]
fn queued_task_cancellation_completes_without_running_the_action() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 2, Duration::from_secs(1)))
        .expect("valid worker pool");
    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(1))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }
    let ran = Arc::new(AtomicBool::new(false));
    let mark_ran = Arc::clone(&ran);
    let cancelled = pool.submit_result(Box::new(move || {
        mark_ran.store(true, Ordering::Release);
        Ok(json!(2))
    }));
    assert!(cancelled.cancel("agent stopped"));
    release.store(true, Ordering::Release);
    assert_eq!(
        cancelled.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Cancelled("agent stopped".to_owned()))
    );
    assert!(!ran.load(Ordering::Acquire));
    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(1)
    );
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn batch_submission_preserves_fifo_order_and_completes_all_handles() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 8, Duration::from_secs(1)))
        .expect("valid worker pool");
    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(0))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }

    let observed = Arc::new(Mutex::new(Vec::new()));
    let actions = (1_u64..=4)
        .map(|value| {
            let observed = Arc::clone(&observed);
            Box::new(move || {
                observed.lock().unwrap().push(value);
                Ok(json!(value))
            }) as l1_kernel_rs::worker::TaskFn
        })
        .collect();
    let handles = pool.submit_result_batch(actions);
    release.store(true, Ordering::Release);

    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(0)
    );
    for (value, handle) in (1_u64..=4).zip(handles) {
        assert_eq!(
            handle.result(Some(Duration::from_secs(1))).unwrap(),
            json!(value)
        );
    }
    assert_eq!(*observed.lock().unwrap(), (1_u64..=4).collect::<Vec<_>>());
    assert_eq!(pool.stats()["rejected"], 0);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn batch_submission_wakes_multiple_workers_without_losing_fifo_work() {
    let pool = WorkerPool::new(WorkerConfig::new(4, 4, 32, Duration::from_secs(1)))
        .expect("valid worker pool");
    let started = Arc::new((Mutex::new(0_usize), Condvar::new()));
    let handles = (0_u64..32)
        .map(|value| {
            let started = Arc::clone(&started);
            Box::new(move || {
                let (lock, wake) = &*started;
                let mut count = lock.lock().unwrap();
                *count += 1;
                wake.notify_all();
                let deadline = Instant::now() + Duration::from_secs(1);
                while *count < 4 {
                    let remaining = deadline.saturating_duration_since(Instant::now());
                    if remaining.is_zero() {
                        return Err("worker wake timeout".to_owned());
                    }
                    let (next, wait) = wake.wait_timeout(count, remaining).unwrap();
                    count = next;
                    if wait.timed_out() && *count < 4 {
                        return Err("worker wake timeout".to_owned());
                    }
                }
                Ok(json!(value))
            }) as l1_kernel_rs::worker::TaskFn
        })
        .collect::<Vec<_>>();
    let handles = pool.submit_result_batch(handles);
    for (value, handle) in (0_u64..32).zip(handles) {
        assert_eq!(
            handle.result(Some(Duration::from_secs(2))).unwrap(),
            json!(value)
        );
    }
    assert_eq!(pool.stats()["rejected"], 0);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn idle_workers_wake_for_new_work_without_waiting_for_idle_timeout() {
    let pool = WorkerPool::new(WorkerConfig::new(4, 4, 8, Duration::from_secs(5)))
        .expect("valid worker pool");
    thread::sleep(Duration::from_millis(20));

    let completed = Arc::new(AtomicUsize::new(0));
    let started = Instant::now();
    let handles = (0..4)
        .map(|_| {
            let completed = Arc::clone(&completed);
            Box::new(move || {
                completed.fetch_add(1, Ordering::Release);
                Ok(json!(true))
            }) as l1_kernel_rs::worker::TaskFn
        })
        .collect::<Vec<_>>();
    let handles = pool.submit_result_batch(handles);
    for handle in handles {
        assert_eq!(
            handle.result(Some(Duration::from_millis(500))).unwrap(),
            json!(true)
        );
    }
    assert_eq!(completed.load(Ordering::Acquire), 4);
    assert!(
        started.elapsed() < Duration::from_secs(1),
        "idle workers did not wake promptly"
    );
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn batch_submission_evicts_oldest_pending_tasks_and_counts_each_eviction() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 2, Duration::from_secs(1)))
        .expect("valid worker pool");
    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(0))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }
    let old = pool.submit_result(Box::new(|| Ok(json!(99))));
    let handles = pool.submit_result_batch(
        (1_u64..=3)
            .map(|value| Box::new(move || Ok(json!(value))) as l1_kernel_rs::worker::TaskFn)
            .collect(),
    );
    assert_eq!(
        old.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Failed(
            "task evicted by backpressure".to_owned(),
        ))
    );
    assert_eq!(
        handles[0].result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Failed(
            "task evicted by backpressure".to_owned(),
        ))
    );

    release.store(true, Ordering::Release);
    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(0)
    );
    assert_eq!(
        handles[1].result(Some(Duration::from_secs(1))).unwrap(),
        json!(2)
    );
    assert_eq!(
        handles[2].result(Some(Duration::from_secs(1))).unwrap(),
        json!(3)
    );
    assert_eq!(pool.stats()["rejected"], 2);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn batch_submission_after_shutdown_completes_every_handle_with_failure() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 4, Duration::from_secs(1)))
        .expect("valid worker pool");
    assert_eq!(pool.shutdown(false, None)["success"], true);
    let handles = pool.submit_result_batch(
        (0..3)
            .map(|_| Box::new(|| Ok(json!(1))) as l1_kernel_rs::worker::TaskFn)
            .collect(),
    );
    assert!(handles.iter().all(|handle| {
        handle.result(Some(Duration::from_secs(1)))
            == Err(TaskHandleError::Failed("pool is shut down".to_owned()))
    }));
    assert_eq!(pool.stats()["rejected"], 3);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn batch_submission_retains_per_handle_cancellation_before_execution() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 4, Duration::from_secs(1)))
        .expect("valid worker pool");
    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(0))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }

    let ran = Arc::new(AtomicBool::new(false));
    let task_ran = Arc::clone(&ran);
    let handles = pool.submit_result_batch(vec![
        Box::new(|| Ok(json!(1))) as l1_kernel_rs::worker::TaskFn,
        Box::new(move || {
            task_ran.store(true, Ordering::Release);
            Ok(json!(2))
        }) as l1_kernel_rs::worker::TaskFn,
    ]);
    assert!(handles[1].cancel("batch item stopped"));
    release.store(true, Ordering::Release);
    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(0)
    );
    assert_eq!(
        handles[0].result(Some(Duration::from_secs(1))).unwrap(),
        json!(1)
    );
    assert_eq!(
        handles[1].result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Cancelled("batch item stopped".to_owned()))
    );
    assert!(!ran.load(Ordering::Acquire));
    assert_eq!(pool.stats()["outcome_cancelled"], 1);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn concurrent_submission_keeps_atomic_metrics_consistent() {
    let pool = Arc::new(
        WorkerPool::new(WorkerConfig::new(2, 4, 64, Duration::from_millis(20)))
            .expect("valid worker pool"),
    );
    let handles = Arc::new(Mutex::new(Vec::new()));
    let producers = (0..4)
        .map(|producer| {
            let pool = Arc::clone(&pool);
            let handles = Arc::clone(&handles);
            thread::spawn(move || {
                for sequence in 0..64 {
                    let handle =
                        pool.submit_result(Box::new(move || Ok(json!([producer, sequence]))));
                    handles.lock().unwrap().push(handle);
                }
            })
        })
        .collect::<Vec<_>>();
    for producer in producers {
        producer.join().expect("producer joins");
    }

    let handles = std::mem::take(&mut *handles.lock().unwrap());
    for handle in handles {
        let result = handle.result(Some(Duration::from_secs(1)));
        assert!(matches!(result, Ok(_) | Err(TaskHandleError::Failed(_))));
    }
    let stats = pool.stats();
    let completed = stats["completed"].as_u64().expect("completed counter");
    let rejected = stats["rejected"].as_u64().expect("rejected counter");
    assert_eq!(completed + rejected, 256);
    assert_eq!(stats["active"], 0);
    assert_eq!(stats["queued"], 0);
    assert!(stats["pool_size"].as_u64().unwrap() >= 2);
    assert!(stats["pool_size"].as_u64().unwrap() <= 4);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn task_deadline_is_reported_at_the_public_worker_boundary() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 2, Duration::from_secs(1)))
        .expect("valid worker pool");
    let handle = pool.submit_result_with_timeout(
        Box::new(|| {
            thread::sleep(Duration::from_millis(10));
            Ok(json!(3))
        }),
        Duration::from_millis(1),
    );
    assert_eq!(
        handle.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::TaskTimeout)
    );
    assert_eq!(pool.stats()["outcome_timed_out"], 1);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

fn configured_pool() -> WorkerPool {
    WorkerPool::new(WorkerConfig::new(1, 2, 4, Duration::from_millis(20)))
        .expect("valid worker pool")
}

#[test]
fn submit_result_returns_json_and_updates_stats() {
    let pool = configured_pool();
    let handle = pool.submit_result(Box::new(|| Ok(json!({"value": 42}))));
    assert_eq!(
        handle.result(Some(Duration::from_secs(1))).unwrap(),
        json!({"value": 42})
    );
    assert_eq!(
        handle.result(Some(Duration::from_millis(1))).unwrap(),
        json!({"value": 42})
    );
    assert_eq!(pool.stats()["completed"], 1);
    assert_eq!(pool.stats()["outcome_cancelled"], 0);
    assert_eq!(pool.stats()["outcome_timed_out"], 0);
    assert_eq!(pool.stats()["outcome_failed"], 0);
    assert!(pool.stats()["queue_wait_ns"].as_u64().is_some());
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn task_done_tracks_completion_without_observing_result_value() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 1, Duration::from_secs(1)))
        .expect("valid worker pool");
    let started = Arc::new(AtomicBool::new(false));
    let release = Arc::new(AtomicBool::new(false));
    let task_started = Arc::clone(&started);
    let task_release = Arc::clone(&release);
    let handle = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!("done"))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }
    assert!(!handle.done());
    release.store(true, Ordering::Release);
    assert_eq!(
        handle.result(Some(Duration::from_secs(1))).unwrap(),
        json!("done")
    );
    assert!(handle.done());
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn submit_result_after_shutdown_completes_handle_with_structured_failure() {
    let pool = configured_pool();
    assert_eq!(pool.shutdown(false, None)["success"], true);

    let handle = pool.submit_result(Box::new(|| Ok(json!("must not run"))));
    assert_eq!(
        handle.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Failed("pool is shut down".to_owned()))
    );
    assert_eq!(pool.stats()["rejected"], 1);
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn single_worker_preserves_fifo_order_across_claim_batches() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 32, Duration::from_secs(1)))
        .expect("valid worker pool");
    let observed = Arc::new(Mutex::new(Vec::new()));
    let handles = (0_u64..16)
        .map(|value| {
            let observed = Arc::clone(&observed);
            pool.submit_result(Box::new(move || {
                observed.lock().unwrap().push(value);
                Ok(json!(value))
            }))
        })
        .collect::<Vec<_>>();
    for (value, handle) in handles.into_iter().enumerate() {
        assert_eq!(
            handle.result(Some(Duration::from_secs(1))).unwrap(),
            json!(value)
        );
    }
    assert_eq!(*observed.lock().unwrap(), (0_u64..16).collect::<Vec<_>>());
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn task_failure_and_panic_complete_handles() {
    let pool = configured_pool();
    let failed = pool.submit_result(Box::new(|| Err("explicit failure".to_owned())));
    assert_eq!(
        failed.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Failed("explicit failure".to_owned()))
    );
    let panicked = pool.submit_result(Box::new(|| -> Result<_, String> { panic!("boom") }));
    assert_eq!(
        panicked.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Failed("task panicked".to_owned()))
    );
    assert_eq!(pool.stats()["outcome_failed"], 2);
    pool.shutdown(true, Some(Duration::from_secs(1)));
}

#[test]
fn queued_task_can_be_cancelled_before_execution() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 2, Duration::from_secs(1)))
        .expect("valid worker pool");
    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(1))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }
    let cancelled = pool.submit_result(Box::new(|| Ok(json!(2))));
    assert!(cancelled.cancel("stopped"));
    release.store(true, Ordering::Release);
    assert_eq!(
        cancelled.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Cancelled("stopped".to_owned()))
    );
    assert_eq!(pool.stats()["outcome_cancelled"], 1);
    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(1)
    );
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn queued_task_deadline_expires_without_running_the_action() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 2, Duration::from_secs(1)))
        .expect("valid worker pool");
    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(1))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }
    let ran = Arc::new(AtomicBool::new(false));
    let mark_ran = Arc::clone(&ran);
    let expired = pool.submit_result_with_timeout(
        Box::new(move || {
            mark_ran.store(true, Ordering::Release);
            Ok(json!(2))
        }),
        Duration::from_millis(1),
    );
    thread::sleep(Duration::from_millis(5));
    release.store(true, Ordering::Release);
    assert_eq!(
        expired.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::TaskTimeout)
    );
    assert_eq!(pool.stats()["outcome_timed_out"], 1);
    assert!(!ran.load(Ordering::Acquire));
    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(1)
    );
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn running_task_timeout_is_distinct_from_result_wait_timeout() {
    let pool = configured_pool();
    let timed = pool.submit_result_with_timeout(
        Box::new(|| {
            thread::sleep(Duration::from_millis(10));
            Ok(json!(3))
        }),
        Duration::from_millis(1),
    );
    assert_eq!(
        timed.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::TaskTimeout)
    );
    assert_eq!(pool.stats()["outcome_timed_out"], 1);

    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let waiting = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(4))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }
    assert_eq!(
        waiting.result(Some(Duration::from_millis(1))),
        Err(TaskHandleError::Timeout)
    );
    release.store(true, Ordering::Release);
    assert_eq!(
        waiting.result(Some(Duration::from_secs(1))).unwrap(),
        json!(4)
    );
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}

#[test]
fn full_queue_evicts_oldest_and_completes_evicted_handle() {
    let pool = WorkerPool::new(WorkerConfig::new(1, 1, 1, Duration::from_secs(1)))
        .expect("valid worker pool");
    let gate = Arc::new(Mutex::new(false));
    let started = Arc::new(Mutex::new(false));
    let hold_gate = Arc::clone(&gate);
    let mark_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        *mark_started.lock().unwrap() = true;
        while !*hold_gate.lock().unwrap() {
            thread::yield_now();
        }
        Ok(json!(0))
    }));
    while !*started.lock().unwrap() {
        thread::yield_now();
    }
    let evicted = pool.submit_result(Box::new(|| Ok(json!(1))));
    let accepted = pool.submit_result(Box::new(|| Ok(json!(2))));
    assert_eq!(
        evicted.result(Some(Duration::from_secs(1))),
        Err(TaskHandleError::Failed(
            "task evicted by backpressure".to_owned()
        ))
    );
    *gate.lock().unwrap() = true;
    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(0)
    );
    assert_eq!(
        accepted.result(Some(Duration::from_secs(1))).unwrap(),
        json!(2)
    );
    assert_eq!(pool.stats()["rejected"], 1);
    pool.shutdown(true, Some(Duration::from_secs(1)));
}

#[test]
fn shutdown_rejects_future_tasks_and_idle_workers_shrink_to_floor() {
    let pool = configured_pool();
    let release = Arc::new(AtomicBool::new(false));
    let started = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let task_started = Arc::clone(&started);
    let running = pool.submit_result(Box::new(move || {
        task_started.store(true, Ordering::Release);
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(0))
    }));
    while !started.load(Ordering::Acquire) {
        thread::yield_now();
    }
    let queued = (0..3)
        .map(|_| pool.submit_result(Box::new(|| Ok(json!(1)))))
        .collect::<Vec<_>>();
    let deadline = std::time::Instant::now() + Duration::from_secs(1);
    while pool.stats()["pool_size"] == json!(1) && std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(pool.stats()["pool_size"], json!(2));
    release.store(true, Ordering::Release);
    assert_eq!(
        running.result(Some(Duration::from_secs(1))).unwrap(),
        json!(0)
    );
    for handle in queued {
        let _ = handle.result(Some(Duration::from_secs(1)));
    }
    let deadline = std::time::Instant::now() + Duration::from_secs(1);
    while pool.stats()["pool_size"] == json!(2) && std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(pool.stats()["pool_size"], json!(1));

    let _ = pool.submit(Box::new(|| Ok(json!(1))));
    pool.shutdown(true, Some(Duration::from_secs(1)));
    assert_eq!(pool.submit(Box::new(|| Ok(json!(2))))["success"], false);
}

#[test]
fn shutdown_timeout_and_stats_do_not_invert_lock_order() {
    let pool = Arc::new(
        WorkerPool::new(WorkerConfig::new(1, 1, 1, Duration::from_secs(1)))
            .expect("valid worker pool"),
    );
    let release = Arc::new(AtomicBool::new(false));
    let task_release = Arc::clone(&release);
    let handle = pool.submit_result(Box::new(move || {
        while !task_release.load(Ordering::Acquire) {
            thread::yield_now();
        }
        Ok(json!(7))
    }));
    thread::sleep(Duration::from_millis(5));

    let shutdown_pool = Arc::clone(&pool);
    let shutdown =
        thread::spawn(move || shutdown_pool.shutdown(true, Some(Duration::from_millis(20))));
    for _ in 0..100 {
        let _ = pool.stats();
    }
    assert_eq!(shutdown.join().unwrap()["success"], false);

    release.store(true, Ordering::Release);
    assert_eq!(
        handle.result(Some(Duration::from_secs(1))).unwrap(),
        json!(7)
    );
    assert_eq!(
        pool.shutdown(true, Some(Duration::from_secs(1)))["success"],
        true
    );
}
