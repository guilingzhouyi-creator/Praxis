//! Independent EventBus mechanism tests for the Rust kernel.

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use l1_kernel_rs::contract::{EventBusStats, JsonObject, JsonValue, Signal};
use l1_kernel_rs::event::{Callback, EventBus, EventBusConfig};

fn bus() -> EventBus {
    EventBus::new(EventBusConfig::new(8, 2, 16, 2))
}

fn signal(event_type: &str) -> Signal {
    Signal {
        signal_type: event_type.to_owned(),
        data: JsonObject::new(),
        sender: String::new(),
        target: String::new(),
        timestamp: 1.0,
    }
}

fn callback<F>(function: F) -> Callback
where
    F: Fn(&Signal) + Send + Sync + 'static,
{
    Arc::new(function)
}

#[test]
fn records_history_and_dispatches_typed_and_wildcard_callbacks() {
    let bus = bus();
    let calls = Arc::new(Mutex::new(Vec::new()));
    let typed_calls = Arc::clone(&calls);
    assert!(bus.on_event(
        "TASK_DONE",
        callback(move |_| typed_calls.lock().unwrap().push("typed")),
    ));
    let wildcard_calls = Arc::clone(&calls);
    bus.on_any(callback(move |_| {
        wildcard_calls.lock().unwrap().push("wildcard")
    }));
    assert_eq!(bus.emit(signal("TASK_DONE")), 2);
    bus.shutdown(true, Some(Duration::from_secs(1)));
    assert_eq!(bus.history(None, 10).len(), 1);
    assert_eq!(calls.lock().unwrap().len(), 2);
    let stats = bus.stats();
    assert_eq!(stats.completed, 2);
    assert!(stats.clean());
}

#[test]
fn bounded_queue_accounts_drops_without_blocking_emitter() {
    let bus = EventBus::new(EventBusConfig::new(8, 1, 0, 2));
    bus.on_any(callback(|_| thread::sleep(Duration::from_millis(10))));
    assert_eq!(bus.emit(signal("TASK_DONE")), 1);
    let stats = bus.stats();
    assert_eq!(stats.submitted, 0);
    assert_eq!(stats.dropped, 1);
    assert_eq!(stats.queue_depth, 0);
    bus.shutdown(true, Some(Duration::from_secs(1)));
}

#[test]
fn dynamic_registry_is_bounded_and_degrades() {
    let bus = bus();
    assert!(bus.register_signal_type("").is_err());
    assert_eq!(bus.emit_event("   ", JsonObject::new(), "test"), 0);
    assert!(bus.register_signal_type("CUSTOM_A").is_ok());
    assert!(bus.register_signal_type("CUSTOM_B").is_ok());
    assert!(bus.register_signal_type("CUSTOM_C").is_err());
    assert!(bus.register_signal_type("TASK_DONE").is_err());
    assert_eq!(bus.emit_event("CUSTOM_C", JsonObject::new(), "test"), 0);
    bus.shutdown(true, Some(Duration::from_secs(1)));
}

#[test]
fn callback_panics_are_contained_and_counted() {
    let async_bus = bus();
    async_bus.on_any(callback(|_| panic!("observer failure")));
    assert_eq!(async_bus.emit(signal("TASK_DONE")), 1);
    async_bus.shutdown(true, Some(Duration::from_secs(1)));
    assert_eq!(async_bus.callback_panics(), 1);
    assert_eq!(async_bus.stats().completed, 1);

    let closed = bus();
    closed.on_any(callback(|_| panic!("closed observer failure")));
    closed.shutdown(false, None);
    assert_eq!(closed.emit(signal("TASK_DONE")), 1);
    assert_eq!(closed.callback_panics(), 1);
}

#[test]
fn shutdown_is_idempotent_and_post_shutdown_emit_is_synchronous() {
    let bus = bus();
    let calls = Arc::new(Mutex::new(0));
    let observed = Arc::clone(&calls);
    bus.on_any(callback(move |_| *observed.lock().unwrap() += 1));
    bus.shutdown(false, None);
    bus.shutdown(true, Some(Duration::from_secs(1)));
    assert_eq!(bus.emit(signal("TASK_DONE")), 1);
    assert_eq!(*calls.lock().unwrap(), 1);
}

#[test]
fn history_filter_and_stats_shape_match_contract() {
    let bus = bus();
    bus.emit(signal("SCOUT_DONE"));
    bus.emit(signal("TASK_DONE"));
    assert_eq!(bus.history(Some("SCOUT_DONE"), 10).len(), 1);
    let stats: EventBusStats = bus.stats();
    assert_eq!(stats.history, 2);
    assert_eq!(stats.drop_rate(), 0.0);
    bus.shutdown(true, Some(Duration::from_secs(1)));
}

#[test]
fn same_signal_channel_preserves_fifo_with_multiple_workers() {
    let bus = EventBus::new(EventBusConfig::new(8, 2, 16, 2));
    let seen = Arc::new(Mutex::new(Vec::new()));
    let first_seen = Arc::clone(&seen);
    bus.on_event(
        "TASK_DONE",
        callback(move |signal| {
            let sequence = signal
                .data
                .get("sequence")
                .and_then(|value| match value {
                    JsonValue::Number(number) => number.as_u64(),
                    _ => None,
                })
                .expect("sequence present");
            if sequence == 1 {
                thread::sleep(Duration::from_millis(20));
            }
            first_seen.lock().unwrap().push(sequence);
        }),
    );
    let mut first = signal("TASK_DONE");
    first.data.insert(
        "sequence".to_owned(),
        JsonValue::Number(serde_json::Number::from(1_u64)),
    );
    let mut second = signal("TASK_DONE");
    second.data.insert(
        "sequence".to_owned(),
        JsonValue::Number(serde_json::Number::from(2_u64)),
    );
    bus.emit(first);
    bus.emit(second);
    bus.shutdown(true, Some(Duration::from_secs(1)));
    assert_eq!(*seen.lock().unwrap(), vec![1, 2]);
}

#[test]
fn a_busy_channel_does_not_starve_other_channels() {
    use std::sync::mpsc::channel;

    let bus = EventBus::new(EventBusConfig::new(8, 2, 16, 2));
    let (a_started_tx, a_started_rx) = channel();
    let (b_started_tx, b_started_rx) = channel();
    let (release_tx, release_rx) = channel();
    let release_rx = Arc::new(Mutex::new(release_rx));
    let release_for_callback = Arc::clone(&release_rx);
    bus.on_event(
        "TASK_ASSIGN",
        callback(move |signal| {
            let sequence = signal
                .data
                .get("sequence")
                .and_then(|value| match value {
                    JsonValue::Number(number) => number.as_u64(),
                    _ => None,
                })
                .expect("sequence present");
            if sequence == 1 {
                a_started_tx.send(()).expect("channel A started");
                release_for_callback
                    .lock()
                    .unwrap()
                    .recv()
                    .expect("channel A released");
            }
        }),
    );
    bus.on_event(
        "TASK_DONE",
        callback(move |_| {
            b_started_tx.send(()).expect("channel B started");
        }),
    );
    let mut a_first = signal("TASK_ASSIGN");
    a_first.data.insert(
        "sequence".to_owned(),
        JsonValue::Number(serde_json::Number::from(1_u64)),
    );
    let mut a_second = signal("TASK_ASSIGN");
    a_second.data.insert(
        "sequence".to_owned(),
        JsonValue::Number(serde_json::Number::from(2_u64)),
    );
    bus.emit(a_first);
    a_started_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("channel A must start before its queue is extended");
    bus.emit(a_second);
    bus.emit(signal("TASK_DONE"));
    b_started_rx
        .recv_timeout(Duration::from_secs(1))
        .expect("channel B must run while channel A is blocked");
    release_tx.send(()).expect("release channel A");
    bus.shutdown(true, Some(Duration::from_secs(1)));
}
