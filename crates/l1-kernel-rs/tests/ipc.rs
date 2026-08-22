//! Independent lock-IPC mechanism tests for the Rust kernel.

use l1_kernel_rs::ipc::{
    IPC_DEFAULT_PRIORITY, IPC_MSG_ID_LENGTH, LockBus, LockChannel, LockMessage, LockOp,
    get_lock_bus, reset_lock_bus,
};
use serde_json::json;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

fn message(op: LockOp, name: &str) -> LockMessage {
    LockMessage::new(op, name).with_agent("agent-1")
}

#[test]
fn message_defaults_and_wire_round_trip_are_stable() {
    let message = message(LockOp::Acquire, "lock:test");
    assert_eq!(message.priority, IPC_DEFAULT_PRIORITY);
    assert_eq!(message.msg_id.len(), IPC_MSG_ID_LENGTH);
    let wire = serde_json::to_value(&message).expect("message json");
    let restored: LockMessage = serde_json::from_value(wire).expect("message decode");
    assert_eq!(restored, message);
    let defaults: LockMessage = serde_json::from_value(json!({
        "op": "ACQUIRE",
        "lock_name": "lock:defaults"
    }))
    .expect("defaults");
    assert_eq!(defaults.priority, IPC_DEFAULT_PRIORITY);
    assert_eq!(defaults.msg_id.len(), IPC_MSG_ID_LENGTH);
}

#[test]
fn send_notifies_handlers_and_stores_reply() {
    let channel = LockChannel::new("lock:test");
    let seen = Arc::new(std::sync::Mutex::new(Vec::new()));
    let seen_handler = Arc::clone(&seen);
    channel.register_handler(move |message| {
        seen_handler
            .lock()
            .expect("seen lock")
            .push(message.lock_name.clone());
        Some(json!({"accepted": true}))
    });
    let message = message(LockOp::Acquire, "lock:test");
    let message_id = channel.send(message.clone());
    assert_eq!(message_id, message.msg_id);
    assert_eq!(*seen.lock().expect("seen lock"), vec!["lock:test"]);
    assert_eq!(
        channel.request(message, Some(Duration::ZERO)),
        json!({"accepted": true})
    );
}

#[test]
fn request_is_woken_by_response_and_timeout_cleans_pending_message() {
    let channel = Arc::new(LockChannel::new("lock:test"));
    let response_channel = Arc::clone(&channel);
    let request_message = message(LockOp::Status, "lock:test");
    let response_id = request_message.msg_id.clone();
    let waiter = thread::spawn(move || {
        response_channel.request(request_message, Some(Duration::from_secs(1)))
    });
    thread::sleep(Duration::from_millis(10));
    channel.respond(&response_id, json!({"granted": true}));
    assert_eq!(waiter.join().expect("waiter"), json!({"granted": true}));
    let timeout_message = message(LockOp::Status, "timeout");
    assert_eq!(
        channel.request(timeout_message, Some(Duration::from_millis(1))),
        json!({})
    );
    assert_eq!(channel.pending_count(), 0);
}

#[test]
fn handler_panics_are_contained_and_backlog_is_bounded() {
    let channel = LockChannel::with_capacity("bounded", 2);
    channel.register_handler(|_| -> Option<serde_json::Value> { panic!("handler failure") });
    channel.send(message(LockOp::Acquire, "bounded"));
    channel.send(message(LockOp::Release, "bounded"));
    channel.send(message(LockOp::Status, "bounded"));
    assert_eq!(channel.pending_count(), 2);
}

#[test]
fn bus_reuses_channels_and_reports_stable_stats() {
    let bus = LockBus::new();
    let first = bus.get_channel("lock:a");
    let second = bus.get_channel("lock:a");
    assert!(Arc::ptr_eq(&first, &second));
    assert!(!bus.channel_exists("lock:b"));
    bus.get_channel("lock:b")
        .send(message(LockOp::Acquire, "lock:b"));
    assert_eq!(bus.stats().get("lock:a"), Some(&0));
    assert_eq!(bus.stats().get("lock:b"), Some(&1));
}

#[test]
fn global_bus_can_be_reset() {
    let first = get_lock_bus();
    let _ = first.get_channel("lock:global");
    reset_lock_bus();
    let second = get_lock_bus();
    assert!(!second.channel_exists("lock:global"));
}
