//! Independent tests for the bounded Rust ProcessPort candidate.

use std::collections::BTreeMap;
use std::time::Duration;

use l1_kernel_rs::contract::{
    PROCESS_ERROR_EXECUTION, PROCESS_ERROR_NONE, PROCESS_ERROR_NOT_FOUND, PROCESS_RETURN_TIMEOUT,
    ProcessOptions,
};
use l1_kernel_rs::process_adapter::{
    ProcessAdapter, ProcessAdapterConfig, ProcessAdapterError, ProcessPort,
};
use l1_kernel_rs::terminal_probe::{TerminalKind, TerminalObservation};

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

fn shell_terminal() -> TerminalObservation {
    #[cfg(unix)]
    {
        TerminalObservation::new(
            "test-shell",
            TerminalKind::Other("posix_test_shell".to_owned()),
            std::env::var("SHELL").unwrap_or_else(|_| "/bin/sh".to_owned()),
            vec!["-c".to_owned()],
            None,
            true,
            false,
            false,
            "utf-8",
            "process-adapter-test",
        )
    }
    #[cfg(windows)]
    {
        TerminalObservation::new(
            "test-shell",
            TerminalKind::Cmd,
            std::env::var("COMSPEC").unwrap_or_else(|_| "cmd.exe".to_owned()),
            vec!["/C".to_owned()],
            None,
            true,
            false,
            false,
            "utf-8",
            "process-adapter-test",
        )
    }
}

#[test]
fn adapter_configuration_is_bounded_and_fail_closed() {
    assert!(matches!(
        ProcessAdapter::new(0),
        Err(ProcessAdapterError::InvalidOutputLimit)
    ));
    assert!(matches!(
        ProcessAdapterConfig::new(0),
        Err(ProcessAdapterError::InvalidOutputLimit)
    ));
    assert_eq!(
        ProcessAdapter::new(128)
            .expect("adapter")
            .config()
            .max_output_bytes,
        128
    );
}

#[test]
fn run_args_and_explicit_terminal_return_plain_success_values() {
    let adapter = ProcessAdapter::new(256).expect("adapter");
    let args = shell_args("printf process-ok");
    let via_args = adapter.run_args(&args, Duration::from_secs(2), None);
    assert!(via_args.ok());
    assert_eq!(via_args.stdout, "process-ok");
    assert_eq!(via_args.error_kind, PROCESS_ERROR_NONE);

    #[cfg(unix)]
    let command = "printf shell-ok";
    #[cfg(windows)]
    let command = "echo shell-ok";
    let via_shell = adapter.run_terminal(command, &shell_terminal(), Duration::from_secs(2), None);
    assert!(via_shell.ok());
    assert!(via_shell.stdout.contains("shell-ok"));
}

#[test]
fn options_replace_environment_and_send_input_without_leaking_process_objects() {
    let adapter = ProcessAdapter::new(256).expect("adapter");
    let mut env = BTreeMap::new();
    env.insert("PRAXIS_PROCESS_TEST".to_owned(), "configured".to_owned());
    let options = ProcessOptions {
        input_text: Some("input-payload".to_owned()),
        env: Some(env),
        ..ProcessOptions::default()
    };

    #[cfg(unix)]
    let args = shell_args("read value; printf '%s:%s' \"$value\" \"$PRAXIS_PROCESS_TEST\"");
    #[cfg(windows)]
    let args = shell_args("set /P value= & echo %value%:%PRAXIS_PROCESS_TEST%");
    let result = adapter.run_args(&args, Duration::from_secs(2), Some(&options));
    assert!(result.ok(), "{result:?}");
    #[cfg(unix)]
    assert_eq!(result.stdout, "input-payload:configured");
    #[cfg(windows)]
    assert!(result.stdout.contains("configured"));
}

#[test]
fn missing_binary_and_nonzero_exit_remain_structured() {
    let adapter = ProcessAdapter::default();
    let missing = adapter.run_args(
        &["praxis-no-such-process-9f5c".to_owned()],
        Duration::from_secs(1),
        None,
    );
    assert_eq!(missing.error_kind, PROCESS_ERROR_NOT_FOUND);
    assert!(!missing.ok());

    #[cfg(unix)]
    let args = shell_args("exit 7");
    #[cfg(windows)]
    let args = shell_args("exit /B 7");
    let exited = adapter.run_args(&args, Duration::from_secs(1), None);
    assert_eq!(exited.returncode, 7);
    assert_eq!(exited.error_kind, PROCESS_ERROR_NONE);
    assert!(!exited.ok());
}

#[test]
fn timeout_kills_bounded_child_and_returns_timeout_value() {
    let adapter = ProcessAdapter::default();
    #[cfg(unix)]
    let args = shell_args("sleep 0.2");
    #[cfg(windows)]
    let args = shell_args("ping -n 3 127.0.0.1 >NUL");
    let result = adapter.run_args(&args, Duration::from_millis(10), None);
    assert_eq!(result.returncode, PROCESS_RETURN_TIMEOUT);
    assert!(result.timed_out);
    assert_eq!(result.error_kind, PROCESS_ERROR_NONE);
}

#[cfg(unix)]
#[test]
fn output_capture_drains_child_streams_and_applies_per_stream_limit() {
    let adapter = ProcessAdapter::new(32).expect("adapter");
    let result = adapter.run_args(
        &shell_args("yes X | head -c 8192"),
        Duration::from_secs(2),
        None,
    );
    assert!(result.ok(), "{result:?}");
    assert!(result.stdout.len() <= 32);
}

#[test]
fn trait_object_uses_the_same_value_boundary() {
    let adapter = ProcessAdapter::default();
    let port: &dyn ProcessPort = &adapter;
    let result = port.run_args(&shell_args("printf trait-ok"), Duration::from_secs(2), None);
    assert_eq!(result.stdout, "trait-ok");
}

#[test]
fn invalid_cwd_is_an_execution_error_not_a_missing_binary() {
    let adapter = ProcessAdapter::default();
    let options = ProcessOptions {
        cwd: Some("/path/that/does/not/exist/praxis".to_owned()),
        ..ProcessOptions::default()
    };
    let result = adapter.run_args(
        &shell_args("printf never-runs"),
        Duration::from_secs(1),
        Some(&options),
    );
    assert_eq!(result.error_kind, PROCESS_ERROR_EXECUTION);
    assert!(!result.ok());
}
