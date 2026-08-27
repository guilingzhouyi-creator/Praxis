//! Public integration coverage for the Rust cancellation boundary.

use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use l1_kernel_rs::cancellation::CancellationToken;

#[test]
fn token_is_cloneable_and_retains_first_reason() {
    let token = CancellationToken::new();
    let clone = token.clone();
    assert!(clone.check().is_ok());
    assert!(token.cancel("shutdown"));
    assert!(!clone.cancel("replacement"));
    assert_eq!(clone.reason().as_deref(), Some("shutdown"));
}

#[test]
fn token_waits_with_a_bounded_timeout() {
    let token = CancellationToken::new();
    assert!(!token.wait(Some(Duration::from_millis(1))));
    assert!(token.cancel("timeout test"));
    assert!(token.wait(Some(Duration::ZERO)));
}

#[test]
fn wait_wakes_all_clones_on_cancellation() {
    let token = CancellationToken::new();
    let (ready_tx, ready_rx) = mpsc::channel();
    let waiter_token = token.clone();
    let waiter = thread::spawn(move || {
        ready_tx.send(()).expect("waiter started");
        waiter_token.wait(None)
    });
    ready_rx.recv().expect("waiter started");
    assert!(token.cancel("request stopped"));
    assert!(waiter.join().expect("waiter joined"));
}
