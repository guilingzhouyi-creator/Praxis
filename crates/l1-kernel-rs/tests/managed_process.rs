//! Independent tests for the bounded managed-process lifecycle candidate.

use std::time::Duration;

use l1_kernel_rs::contract::ProcessOptions;
use l1_kernel_rs::managed_process::{
    ManagedProcessBook, ManagedProcessError, ManagedProcessState, ManagedWaitResult,
};
use l1_kernel_rs::process_adapter::ProcessAdapterConfig;

fn shell_args(command: &str) -> Vec<String> {
    #[cfg(unix)]
    {
        vec!["/bin/sh".to_owned(), "-c".to_owned(), command.to_owned()]
    }
    #[cfg(windows)]
    {
        vec!["cmd.exe".to_owned(), "/C".to_owned(), command.to_owned()]
    }
}

fn book(capacity: u32) -> ManagedProcessBook {
    ManagedProcessBook::new(ProcessAdapterConfig::new(256).expect("config"), capacity)
        .expect("book")
}

#[test]
fn capacity_and_configuration_fail_closed() {
    let config = ProcessAdapterConfig {
        max_output_bytes: 0,
        poll_interval: Duration::from_millis(1),
    };
    assert!(matches!(
        ManagedProcessBook::new(config, 1),
        Err(ManagedProcessError::InvalidOutputLimit)
    ));
    let managed = book(1);
    let first = managed
        .spawn_args(&shell_args("sleep 0.2"), None)
        .expect("first child");
    assert_eq!(managed.active_count(), 1);
    assert_eq!(
        managed.spawn_args(&shell_args("printf blocked"), None),
        Err(ManagedProcessError::Capacity)
    );
    managed
        .terminate(first, Duration::from_secs(1))
        .expect("terminate");
    managed.reap(first).expect("reap");
}

#[test]
fn stdin_wait_snapshot_and_reap_preserve_public_lifecycle() {
    let managed = book(2);
    let handle = managed
        .spawn_args(&shell_args("read value; printf '%s' \"$value\""), None)
        .expect("child");
    assert_eq!(managed.write_stdin(handle, b"managed-input\n"), Ok(14));
    managed.close_stdin(handle).expect("close stdin");
    let waited = managed.wait(handle, Duration::from_secs(2)).expect("wait");
    let ManagedWaitResult::Finished(result) = waited else {
        panic!("child did not finish")
    };
    assert!(result.ok(), "{result:?}");
    assert_eq!(result.stdout, "managed-input");
    let snapshot = managed.snapshot(handle).expect("snapshot");
    assert_eq!(snapshot.state, ManagedProcessState::Exited);
    assert_eq!(snapshot.returncode, Some(0));
    managed.reap(handle).expect("reap");
    assert_eq!(managed.active_count(), 0);
    assert_eq!(
        managed.snapshot(handle),
        Err(ManagedProcessError::UnknownHandle)
    );
}

#[test]
fn observer_timeout_does_not_reap_and_terminate_is_explicit() {
    let managed = book(1);
    let handle = managed
        .spawn_args(&shell_args("sleep 0.2"), None)
        .expect("child");
    assert_eq!(
        managed.wait(handle, Duration::ZERO).expect("poll"),
        ManagedWaitResult::Pending
    );
    assert_eq!(
        managed.snapshot(handle).expect("snapshot").state,
        ManagedProcessState::Running
    );
    let result = managed
        .terminate(handle, Duration::from_secs(1))
        .expect("terminate");
    assert!(!result.ok());
    assert_eq!(
        managed.snapshot(handle).expect("snapshot").state,
        ManagedProcessState::Killed
    );
    managed.reap(handle).expect("reap");
}

#[test]
fn generation_reuse_rejects_old_handle_after_reap() {
    let managed = book(1);
    let first = managed
        .spawn_args(&shell_args("printf first"), None)
        .expect("first");
    let first_result = managed.wait(first, Duration::from_secs(1)).expect("wait");
    assert!(matches!(first_result, ManagedWaitResult::Finished(_)));
    managed.reap(first).expect("reap first");
    let second = managed
        .spawn_args(&shell_args("printf second"), None)
        .expect("second");
    assert_ne!(first.raw(), second.raw());
    assert_eq!(
        managed.snapshot(first),
        Err(ManagedProcessError::UnknownHandle)
    );
    managed
        .terminate(second, Duration::from_secs(1))
        .expect("stop");
    managed.reap(second).expect("reap second");
}

#[cfg(unix)]
#[test]
fn output_is_drained_and_retained_per_stream() {
    let managed =
        ManagedProcessBook::new(ProcessAdapterConfig::new(32).expect("config"), 1).expect("book");
    let handle = managed
        .spawn_args(&shell_args("yes X | head -c 8192"), None)
        .expect("child");
    let ManagedWaitResult::Finished(result) =
        managed.wait(handle, Duration::from_secs(2)).expect("wait")
    else {
        panic!("child did not finish")
    };
    assert!(result.stdout.len() <= 32);
    managed.reap(handle).expect("reap");
}

#[test]
fn invalid_commands_and_cwd_are_structured() {
    let managed = book(1);
    assert!(matches!(
        managed.spawn_args(&["praxis-managed-missing-4e1d".to_owned()], None),
        Err(ManagedProcessError::NotFound(_))
    ));
    let options = ProcessOptions {
        cwd: Some("/path/that/does/not/exist/praxis-managed".to_owned()),
        ..ProcessOptions::default()
    };
    assert!(matches!(
        managed.spawn_args(&shell_args("printf never"), Some(&options)),
        Err(ManagedProcessError::InvalidCwd(_))
    ));
}
