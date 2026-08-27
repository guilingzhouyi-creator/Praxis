//! Independent channel mechanism tests for the Rust kernel.

use std::sync::Arc;
use std::thread;
use std::time::Duration;

use l1_kernel_rs::channel::RingChannel;
use serde_json::json;

#[test]
fn fifo_put_get_peek_and_drain_preserve_json_values() {
    let channel = RingChannel::new(4, false).expect("valid channel");
    assert!(channel.put(json!("a"), Some(Duration::from_millis(10))));
    assert!(channel.put(json!({"n": 2}), Some(Duration::from_millis(10))));
    assert_eq!(
        channel.peek(Some(Duration::from_millis(10))),
        Some(json!("a"))
    );
    assert_eq!(
        channel.get(Some(Duration::from_millis(10))),
        Some(json!("a"))
    );
    assert_eq!(channel.drain(), vec![json!({"n": 2})]);
    assert_eq!(channel.size(), 0);
}

#[test]
fn bounded_put_times_out_and_overwrite_discards_oldest() {
    let channel = RingChannel::new(1, false).expect("valid channel");
    assert!(channel.put(json!(1), None));
    assert!(!channel.put(json!(2), Some(Duration::from_millis(5))));

    let overwrite = RingChannel::new(2, true).expect("valid overwrite channel");
    assert!(overwrite.put(json!("a"), None));
    assert!(overwrite.put(json!("b"), None));
    assert!(overwrite.put(json!("c"), None));
    assert_eq!(overwrite.get(None), Some(json!("b")));
    assert_eq!(overwrite.get(None), Some(json!("c")));
}

#[test]
fn close_unblocks_waiters_and_rejects_future_puts() {
    let channel = Arc::new(RingChannel::new(1, false).expect("valid channel"));
    let waiting = Arc::clone(&channel);
    let join = thread::spawn(move || waiting.get(None));
    thread::sleep(Duration::from_millis(5));
    channel.close();
    assert_eq!(join.join().expect("waiter joins"), None);
    assert!(!channel.put(json!("closed"), None));
    assert!(channel.is_closed());
}

#[test]
fn drain_wakes_all_producers_for_all_released_slots() {
    use std::sync::mpsc::channel as message_channel;

    let channel = Arc::new(RingChannel::new(2, false).expect("valid channel"));
    assert!(channel.put(json!("held-a"), None));
    assert!(channel.put(json!("held-b"), None));
    let (done_tx, done_rx) = message_channel();
    let mut joins = Vec::new();
    for value in ["next-a", "next-b"] {
        let producer = Arc::clone(&channel);
        let done = done_tx.clone();
        joins.push(thread::spawn(move || {
            assert!(producer.put(json!(value), None));
            done.send(()).expect("producer reports completion");
        }));
    }
    drop(done_tx);
    thread::sleep(Duration::from_millis(5));
    assert!(done_rx.try_recv().is_err());
    assert_eq!(channel.drain().len(), 2);
    assert!(done_rx.recv_timeout(Duration::from_secs(1)).is_ok());
    assert!(done_rx.recv_timeout(Duration::from_secs(1)).is_ok());
    for join in joins {
        join.join().expect("producer joins");
    }
    assert_eq!(channel.size(), 2);
}

#[test]
fn invalid_capacity_and_utilization_are_explicit() {
    assert!(RingChannel::new(0, false).is_err());
    let channel = RingChannel::new(4, false).expect("valid channel");
    assert_eq!(channel.utilization(), 0.0);
    channel.put(json!(1), None);
    assert_eq!(channel.utilization(), 0.25);
}
