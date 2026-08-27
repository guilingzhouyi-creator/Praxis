//! Independent synchronization mechanism tests for the Rust kernel.

use l1_kernel_rs::cancellation::CancellationToken;
use l1_kernel_rs::sync::{Barrier, Condition, Mutex, RwLock, Semaphore};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

#[test]
fn mutex_matches_reentrant_python_shape() {
    let mutex = Mutex::new("mutex", Duration::from_millis(50));
    assert_eq!(mutex.acquire("agent-a", 5.0, true)["success"], true);
    assert_eq!(mutex.acquire("agent-a", 5.0, true)["recursion"], 2);
    assert_eq!(mutex.release("agent-a")["recursion"], 1);
    assert_eq!(mutex.release("agent-a")["priority_restored"], false);
    assert_eq!(mutex.status()["state"], "FREE");
}

#[test]
fn mutex_rejects_non_owner_and_nonblocking_contention() {
    let mutex = Mutex::new("mutex", Duration::from_millis(20));
    assert_eq!(mutex.acquire("owner", 5.0, true)["success"], true);
    assert_eq!(mutex.release("intruder")["success"], false);
    assert_eq!(
        mutex.acquire("waiter", 5.0, false)["error"],
        "lock contended"
    );
    assert_eq!(mutex.force_unlock()["success"], true);
}

#[test]
fn mutex_timeout_removes_waiter() {
    let mutex = Arc::new(Mutex::new("mutex", Duration::from_millis(10)));
    assert_eq!(mutex.acquire("owner", 5.0, true)["success"], true);
    let waiting = Arc::clone(&mutex);
    let join = thread::spawn(move || waiting.acquire("waiter", 5.0, true));
    assert_eq!(join.join().expect("waiter")["error"], "timeout");
    assert_eq!(mutex.status()["waiter_count"], 0);
}

#[test]
fn mutex_priority_callback_is_observable() {
    let observed = Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
    let sink = Arc::clone(&observed);
    let mutex = Mutex::new("mutex", Duration::from_millis(10)).with_boost_callback(Arc::new(
        move |owner, old, new| {
            sink.lock()
                .expect("callback lock")
                .push(format!("{owner}:{old}:{new}"));
        },
    ));
    assert_eq!(mutex.acquire("owner", 5.0, true)["success"], true);
    assert_eq!(mutex.acquire("waiter", 1.0, false)["success"], false);
    assert_eq!(observed.lock().expect("observed lock").len(), 1);
}

#[test]
fn mutex_priority_callback_panic_does_not_poison_lock() {
    let mutex = Mutex::new("mutex-panic", Duration::from_millis(20))
        .with_boost_callback(Arc::new(|_, _, _| panic!("telemetry failure")));
    assert_eq!(mutex.acquire("owner", 5.0, true)["success"], true);
    assert_eq!(
        mutex.acquire("waiter", 1.0, false)["error"],
        "lock contended"
    );
    assert_eq!(mutex.release("owner")["success"], true);
    assert_eq!(mutex.acquire("next", 5.0, false)["success"], true);
}

#[test]
fn semaphore_matches_capacity_and_timeout_shape() {
    let semaphore = Semaphore::new(
        "semaphore",
        1,
        Duration::from_millis(10),
        Duration::from_millis(2),
    );
    assert_eq!(semaphore.acquire("agent-a", false)["remaining"], 0);
    assert_eq!(semaphore.acquire("agent-b", false)["error"], "no capacity");
    assert_eq!(semaphore.acquire("agent-b", true)["error"], "timeout");
    assert_eq!(semaphore.status()["waiters"], 0);
    assert_eq!(semaphore.release("agent-a")["remaining"], 1);
    assert_eq!(semaphore.acquire("agent-b", false)["success"], true);
}

#[test]
fn barrier_releases_one_releaser_and_one_waiter() {
    let barrier = Arc::new(Barrier::new("barrier", 2, Duration::from_millis(100)));
    let waiting = Arc::clone(&barrier);
    let join = thread::spawn(move || waiting.wait("agent-a"));
    thread::sleep(Duration::from_millis(5));
    let second = barrier.wait("agent-b");
    let first = join.join().expect("barrier waiter");
    assert_eq!(second["role"], "releaser");
    assert_eq!(first["role"], "waiter");
    assert_eq!(barrier.reset()["success"], true);
}

#[test]
fn condition_buffers_signals_and_wakes_waiters() {
    let condition = Condition::new("condition", Duration::from_millis(20));
    assert_eq!(condition.signal("agent-a")["wakeup"], 0);
    assert_eq!(condition.wait("agent-b", None)["timed_out"], false);
    let condition = Arc::new(Condition::new("condition", Duration::from_millis(100)));
    let waiting = Arc::clone(&condition);
    let join = thread::spawn(move || waiting.wait("agent-a", None));
    thread::sleep(Duration::from_millis(5));
    assert_eq!(condition.signal("agent-b")["success"], true);
    assert_eq!(join.join().expect("condition waiter")["timed_out"], false);
}

#[test]
fn rwlock_preserves_writer_preference_and_reentrant_reads() {
    let lock = Arc::new(RwLock::new(
        "rwlock",
        Duration::from_millis(500),
        Duration::from_millis(2),
    ));
    assert_eq!(lock.read_lock("reader")["success"], true);
    assert_eq!(lock.read_lock("reader")["readers"], 2);
    let waiting = Arc::clone(&lock);
    let join = thread::spawn(move || waiting.write_lock("writer"));
    for _ in 0..200 {
        if lock.status()["write_waiters"] == 1 {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(lock.status()["write_waiters"], 1);
    assert_eq!(
        lock.read_lock_with_timeout("new-reader", Duration::from_millis(10))["error"],
        "timeout"
    );
    assert_eq!(lock.unlock("reader")["readers"], 1);
    assert_eq!(lock.unlock("reader")["readers"], 0);
    assert_eq!(join.join().expect("writer")["success"], true);
    assert_eq!(lock.status()["writer"], "writer");
    assert_eq!(lock.unlock("writer")["success"], true);
}

#[test]
fn rwlock_tracks_reentrant_write_depth_and_rejects_empty_identity() {
    let lock = RwLock::new(
        "rwlock-depth",
        Duration::from_millis(20),
        Duration::from_millis(1),
    );
    assert_eq!(lock.write_lock("writer")["depth"], 1);
    assert_eq!(lock.write_lock("writer")["depth"], 2);
    assert_eq!(lock.status()["writer_depth"], 2);
    assert_eq!(lock.unlock("writer")["depth"], 1);
    assert_eq!(lock.status()["writer"], "writer");
    assert_eq!(lock.unlock("writer")["success"], true);
    assert_eq!(lock.status()["writer_depth"], 0);
    assert_eq!(lock.read_lock("")["error"], "invalid agent_id");
    assert_eq!(lock.write_lock("")["error"], "invalid agent_id");
    assert_eq!(lock.unlock("")["error"], "invalid agent_id");
}

#[test]
fn rwlock_serves_writers_in_ticket_order() {
    let lock = Arc::new(RwLock::new(
        "rwlock-fairness",
        Duration::from_secs(1),
        Duration::from_millis(1),
    ));
    assert_eq!(lock.read_lock("reader")["success"], true);
    let (first_acquired_tx, first_acquired_rx) = std::sync::mpsc::channel();
    let (first_release_tx, first_release_rx) = std::sync::mpsc::channel();
    let first_lock = Arc::clone(&lock);
    let first = thread::spawn(move || {
        let result = first_lock.write_lock("writer-a");
        first_acquired_tx.send(()).expect("first writer acquired");
        first_release_rx.recv().expect("first writer released");
        assert_eq!(first_lock.unlock("writer-a")["success"], true);
        result
    });
    for _ in 0..200 {
        if lock.status()["write_waiters"] == 1 {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(lock.status()["write_waiters"], 1);
    let (second_acquired_tx, second_acquired_rx) = std::sync::mpsc::channel();
    let second_lock = Arc::clone(&lock);
    let second = thread::spawn(move || {
        let result = second_lock.write_lock("writer-b");
        second_acquired_tx.send(()).expect("second writer acquired");
        assert_eq!(second_lock.unlock("writer-b")["success"], true);
        result
    });
    for _ in 0..200 {
        if lock.status()["write_waiters"] == 2 {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(lock.status()["write_waiters"], 2);
    assert_eq!(lock.unlock("reader")["readers"], 0);
    first_acquired_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("first writer gets ticket");
    assert!(
        second_acquired_rx
            .recv_timeout(Duration::from_millis(20))
            .is_err()
    );
    first_release_tx.send(()).expect("release first writer");
    second_acquired_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("second writer follows");
    assert_eq!(first.join().expect("first writer joins")["success"], true);
    assert_eq!(second.join().expect("second writer joins")["success"], true);
}

#[test]
fn rwlock_cancellation_removes_ticket_and_wakes_successor() {
    let lock = Arc::new(RwLock::new(
        "rwlock-cancellation",
        Duration::from_secs(1),
        Duration::from_millis(1),
    ));
    assert_eq!(lock.read_lock("reader")["success"], true);
    let cancellation = CancellationToken::new();
    let first_lock = Arc::clone(&lock);
    let first_token = cancellation.clone();
    let first =
        thread::spawn(move || first_lock.write_lock_with_cancellation("writer-a", &first_token));
    for _ in 0..200 {
        if lock.status()["write_waiters"] == 1 {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(lock.status()["write_waiters"], 1);
    assert!(cancellation.cancel("agent stopped"));
    assert_eq!(
        first.join().expect("cancelled writer joins")["error"],
        "cancelled"
    );
    assert_eq!(lock.status()["write_waiters"], 0);
    let second_lock = Arc::clone(&lock);
    let second = thread::spawn(move || {
        let result = second_lock.write_lock("writer-b");
        assert_eq!(second_lock.unlock("writer-b")["success"], true);
        result
    });
    for _ in 0..200 {
        if lock.status()["write_waiters"] == 1 {
            break;
        }
        thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(lock.status()["write_waiters"], 1);
    assert_eq!(lock.unlock("reader")["readers"], 0);
    assert_eq!(second.join().expect("successor joins")["success"], true);
}
