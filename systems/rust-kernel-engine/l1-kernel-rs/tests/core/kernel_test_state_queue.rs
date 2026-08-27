//! Public integration coverage for cancellable Rust queue waits.

use std::sync::Arc;

use l1_kernel_rs::cancellation::CancellationToken;
use l1_kernel_rs::state_queue::{
    BoundedWorkQueue, ProcessHandleAllocator, QueueWaitError, ShardedStateStore, TaskState,
    WorkItem,
};
use l1_kernel_rs::substrate::{ProcessHandle, QueueMetrics};

fn handle(slot: u32, generation: u32) -> ProcessHandle {
    ProcessHandle::new(slot, generation).expect("valid handle")
}

#[test]
fn cancelled_wait_returns_without_claiming_work() {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = BoundedWorkQueue::new(1, Arc::clone(&metrics)).expect("valid queue");
    let handle = ProcessHandle::new(7, 1).expect("valid process handle");
    assert!(queue.try_push(WorkItem {
        handle,
        sequence: 2
    }));
    let token = CancellationToken::new();
    assert!(token.cancel("stop"));
    assert_eq!(
        queue.pop_wait_with_cancellation(&token),
        Err(QueueWaitError::Cancelled)
    );
    assert_eq!(queue.len(), 1);
    assert_eq!(queue.metrics().submitted, 1);
}

#[test]
fn active_wait_claims_an_available_item() {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = BoundedWorkQueue::new(1, Arc::clone(&metrics)).expect("valid queue");
    let handle = ProcessHandle::new(8, 1).expect("valid process handle");
    assert!(queue.try_push(WorkItem {
        handle,
        sequence: 3
    }));
    let item = queue
        .pop_wait_with_cancellation(&CancellationToken::new())
        .expect("available work");
    assert_eq!(item.sequence, 3);
    queue.record_complete();
}

#[test]
fn batch_completion_updates_depth_without_underflow() {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = BoundedWorkQueue::new(4, Arc::clone(&metrics)).expect("valid queue");
    let handle = ProcessHandle::new(9, 1).expect("valid process handle");
    for sequence in 0..3 {
        assert!(queue.try_push(WorkItem { handle, sequence }));
    }
    let mut batch = Vec::new();
    assert_eq!(queue.drain_batch(3, &mut batch), 3);
    queue.record_complete_batch(batch.len());
    queue.record_complete_batch(2);
    let snapshot = queue.metrics();
    assert_eq!(snapshot.completed, 5);
    assert_eq!(snapshot.queue_depth, 0);
}

#[test]
fn process_handle_allocator_reuses_slots_with_new_generations() {
    let allocator = ProcessHandleAllocator::new(2).expect("valid allocator");
    let first = allocator.allocate().expect("first handle");
    let second = allocator.allocate().expect("second handle");
    assert!(allocator.is_current(first));
    assert_eq!(allocator.active_count(), 2);
    assert!(allocator.allocate().is_err());

    allocator.release(first).expect("release first handle");
    assert!(!allocator.is_current(first));
    assert_eq!(allocator.active_count(), 1);
    let reused = allocator.allocate().expect("reused handle");
    assert_eq!(reused.slot(), first.slot());
    assert_eq!(reused.generation(), first.generation() + 1);
    assert!(!allocator.is_current(first));
    assert!(allocator.is_current(reused));

    assert!(allocator.release(first).is_err());
    allocator.release(second).expect("release second handle");
    allocator.release(reused).expect("release reused handle");
    assert_eq!(allocator.active_count(), 0);
}

#[test]
fn process_handle_allocator_rejects_zero_capacity_and_duplicate_release() {
    assert!(ProcessHandleAllocator::new(0).is_err());
    let allocator = ProcessHandleAllocator::new(1).expect("valid allocator");
    let handle = allocator.allocate().expect("handle");
    allocator.release(handle).expect("release");
    assert!(allocator.release(handle).is_err());
}

#[test]
fn sharded_store_rejects_stale_generations_and_tracks_transitions() {
    let store = ShardedStateStore::new(2).expect("valid store");
    let current = handle(3, 1);
    let stale = handle(3, 2);
    assert_eq!(store.shard_for(current), 1);
    store.insert(current, TaskState::Ready).expect("insert");
    assert!(store.insert(stale, TaskState::Ready).is_err());
    let running = store
        .transition(current, TaskState::Ready, TaskState::Running)
        .expect("ready to running");
    assert_eq!(running.transition_seq, 1);
    assert_eq!(running.state, TaskState::Running);
    assert!(
        store
            .transition(stale, TaskState::Running, TaskState::Ready)
            .is_err()
    );
    assert_eq!(store.len(), 1);
}

#[test]
fn stopped_state_is_terminal_until_explicit_resume() {
    let store = ShardedStateStore::new(1).expect("valid store");
    let process = handle(1, 1);
    store.insert(process, TaskState::Ready).expect("insert");
    store
        .transition(process, TaskState::Ready, TaskState::Stopped)
        .expect("stop");
    assert!(
        store
            .transition(process, TaskState::Stopped, TaskState::Running)
            .is_err()
    );
    store
        .transition(process, TaskState::Stopped, TaskState::Ready)
        .expect("resume to ready");
    assert_eq!(store.get(process).expect("record").state, TaskState::Ready);
}

#[test]
fn bounded_queue_rejects_at_capacity_and_reports_completion() {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = BoundedWorkQueue::new(1, Arc::clone(&metrics)).expect("valid queue");
    let process = handle(2, 1);
    assert!(queue.try_push(WorkItem {
        handle: process,
        sequence: 1,
    }));
    assert!(!queue.try_push(WorkItem {
        handle: process,
        sequence: 2,
    }));
    assert_eq!(queue.len(), 1);
    assert_eq!(queue.try_pop().expect("item").sequence, 1);
    queue.record_complete();
    assert!(queue.is_empty());
    let snapshot = queue.metrics();
    assert_eq!(snapshot.submitted, 1);
    assert_eq!(snapshot.rejected, 1);
    assert_eq!(snapshot.queue_depth, 0);
    assert_eq!(snapshot.peak_queue_depth, 1);
}

#[test]
fn blocking_queue_waits_for_capacity_and_wakes_after_pop() {
    use std::sync::mpsc::channel;
    use std::time::Duration;

    let metrics = Arc::new(QueueMetrics::new());
    let queue = Arc::new(BoundedWorkQueue::new(1, Arc::clone(&metrics)).expect("valid queue"));
    let process = handle(4, 1);
    queue.push_wait(WorkItem {
        handle: process,
        sequence: 1,
    });
    let (started_tx, started_rx) = channel();
    let (finished_tx, finished_rx) = channel();
    let producer_queue = Arc::clone(&queue);
    let producer = std::thread::spawn(move || {
        started_tx.send(()).expect("started signal");
        producer_queue.push_wait(WorkItem {
            handle: process,
            sequence: 2,
        });
        finished_tx.send(()).expect("finished signal");
    });
    started_rx.recv().expect("producer started");
    assert!(finished_rx.recv_timeout(Duration::from_millis(20)).is_err());
    assert_eq!(queue.try_pop().expect("first item").sequence, 1);
    finished_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("producer wakes after pop");
    producer.join().expect("producer joins");
    assert_eq!(queue.pop_wait().sequence, 2);
    queue.record_complete();
    queue.record_complete();
    assert_eq!(queue.metrics().rejected, 0);
}

#[test]
fn drain_batch_preserves_fifo_order() {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = BoundedWorkQueue::new(4, Arc::clone(&metrics)).expect("valid queue");
    let process = handle(5, 1);
    for sequence in 0..4 {
        queue.push_wait(WorkItem {
            handle: process,
            sequence,
        });
    }
    let mut batch = Vec::new();
    assert_eq!(queue.drain_batch(3, &mut batch), 3);
    assert_eq!(
        batch.iter().map(|item| item.sequence).collect::<Vec<_>>(),
        [0, 1, 2]
    );
    assert_eq!(queue.try_pop().expect("remaining item").sequence, 3);
}

#[test]
fn cancellable_wait_stops_without_claiming_work() {
    use std::sync::mpsc::channel;

    let metrics = Arc::new(QueueMetrics::new());
    let queue = Arc::new(BoundedWorkQueue::new(2, Arc::clone(&metrics)).expect("valid queue"));
    let cancellation = CancellationToken::new();
    let (started_tx, started_rx) = channel();
    let waiter_queue = Arc::clone(&queue);
    let waiter_token = cancellation.clone();
    let waiter = std::thread::spawn(move || {
        started_tx.send(()).expect("waiter started");
        waiter_queue.pop_wait_with_cancellation(&waiter_token)
    });
    started_rx.recv().expect("waiter started");
    assert!(cancellation.cancel("process stopped"));
    assert_eq!(
        waiter.join().expect("waiter joins"),
        Err(QueueWaitError::Cancelled)
    );
    assert!(queue.is_empty());
    assert_eq!(queue.metrics().submitted, 0);
}

#[test]
fn cancellable_wait_claims_fifo_work_before_cancellation() {
    let metrics = Arc::new(QueueMetrics::new());
    let queue = BoundedWorkQueue::new(2, Arc::clone(&metrics)).expect("valid queue");
    let process = handle(6, 1);
    queue.try_push(WorkItem {
        handle: process,
        sequence: 9,
    });
    let item = queue
        .pop_wait_with_cancellation(&CancellationToken::new())
        .expect("work is available");
    assert_eq!(item.sequence, 9);
    queue.record_complete();
}

#[test]
fn empty_state_and_zero_capacity_are_explicit() {
    let store = ShardedStateStore::new(1).expect("valid store");
    assert!(store.is_empty());
    assert!(BoundedWorkQueue::new(0, Arc::new(QueueMetrics::new())).is_err());
}

#[test]
fn sharded_state_survives_parallel_insert_and_transitions() {
    let store = Arc::new(ShardedStateStore::new(4).expect("valid store"));
    let workers = (0..4)
        .map(|worker| {
            let store = Arc::clone(&store);
            std::thread::spawn(move || {
                for offset in 0..16 {
                    let process = handle(worker * 16 + offset, 1);
                    store.insert(process, TaskState::Ready).expect("insert");
                    store
                        .transition(process, TaskState::Ready, TaskState::Running)
                        .expect("run");
                    store
                        .transition(process, TaskState::Running, TaskState::Ready)
                        .expect("yield");
                }
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().expect("state worker joins");
    }
    assert_eq!(store.len(), 64);
}
