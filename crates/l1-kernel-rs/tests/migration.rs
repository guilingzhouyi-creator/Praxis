//! Independent migration-runner tests for the Rust kernel.

use std::sync::{Arc, Mutex};

use l1_kernel_rs::migration::{MigrationRunner, SCHEMA_VERSION, reset_migrations, run_pending};

#[test]
fn pending_migrations_are_sorted_and_bounded_by_target() {
    let runner = MigrationRunner::new();
    let mut calls = Vec::new();
    runner.register("20260731.1", || Ok(()));
    runner.register("20260730.2", || Ok(()));
    runner.register("20260801.1", || Ok(()));
    let report = runner.run_pending("20260730.1", "20260731.1");
    calls.extend(report.applied.clone());
    assert_eq!(calls, vec!["20260730.2", "20260731.1"]);
    assert!(report.errors.is_empty());
}

#[test]
fn failure_stops_later_migrations_and_panic_is_structured() {
    let runner = MigrationRunner::new();
    runner.register("20260731.1", || Err("disk unavailable".to_owned()));
    runner.register("20260732.1", || panic!("unexpected"));
    let report = runner.run_pending("20260730.1", "20260732.1");
    assert!(report.applied.is_empty());
    assert_eq!(report.errors[0].version, "20260731.1");
    assert_eq!(report.errors[0].error, "disk unavailable");

    let panic_runner = MigrationRunner::new();
    panic_runner.register("20260732.1", || panic!("unexpected"));
    let panic_report = panic_runner.run_pending("20260731.1", "20260732.1");
    assert_eq!(panic_report.errors[0].version, "20260732.1");
    assert_eq!(panic_report.errors[0].error, "migration callback panicked");
}

#[test]
fn duplicate_versions_run_in_registration_order() {
    let runner = MigrationRunner::new();
    let calls = Arc::new(Mutex::new(Vec::new()));
    let first_calls = Arc::clone(&calls);
    runner.register("20260731.1", move || {
        first_calls.lock().unwrap().push("first");
        Ok(())
    });
    let second_calls = Arc::clone(&calls);
    runner.register("20260731.1", move || {
        second_calls.lock().unwrap().push("second");
        Ok(())
    });
    let report = runner.run_pending("20260730.1", "20260731.1");
    assert_eq!(report.applied, vec!["20260731.1", "20260731.1"]);
    assert_eq!(*calls.lock().unwrap(), vec!["first", "second"]);
}

#[test]
fn global_runner_can_be_reset() {
    reset_migrations();
    let report = run_pending(SCHEMA_VERSION);
    assert!(report.applied.is_empty());
    assert!(report.errors.is_empty());
    reset_migrations();
}
