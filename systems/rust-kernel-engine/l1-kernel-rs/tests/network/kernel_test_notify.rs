//! Independent notification-buffer tests for the Rust kernel.

use l1_kernel_rs::notify::NotificationBuffer;
use serde_json::json;

#[test]
fn buffer_is_bounded_and_reads_newest_first() {
    let buffer = NotificationBuffer::new(2).expect("valid buffer");
    buffer
        .publish("first", json!({"n": 1}), 1.0)
        .expect("publish");
    buffer
        .publish("second", json!({"n": 2}), 2.0)
        .expect("publish");
    buffer
        .publish("third", json!({"n": 3}), 3.0)
        .expect("publish");
    let recent = buffer.recent(0);
    assert_eq!(recent[0].topic, "third");
    assert_eq!(recent[1].topic, "second");
    assert_eq!(buffer.stats().dropped, 1);
}

#[test]
fn limits_and_reset_are_explicit() {
    let buffer = NotificationBuffer::new(2).expect("valid buffer");
    buffer.publish("a", json!(null), 1.0).expect("publish");
    buffer.publish("b", json!(null), 2.0).expect("publish");
    assert_eq!(buffer.recent(1).len(), 1);
    buffer.clear();
    assert_eq!(buffer.stats().queued, 0);
    assert_eq!(buffer.stats().dropped, 0);
    buffer.publish("c", json!(null), 3.0).expect("publish");
    buffer.publish("d", json!(null), 4.0).expect("publish");
    buffer.publish("e", json!(null), 5.0).expect("publish");
    buffer.reset();
    assert_eq!(buffer.stats().queued, 0);
    assert_eq!(buffer.stats().dropped, 0);
}

#[test]
fn invalid_capacity_and_timestamp_fail_closed() {
    assert!(NotificationBuffer::new(0).is_err());
    let buffer = NotificationBuffer::default();
    assert!(buffer.publish("bad", json!(null), f64::NAN).is_err());
}
