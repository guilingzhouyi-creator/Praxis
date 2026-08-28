//! Rust-owned bounded one-shot process adapter candidate.
//!
//! This module implements the language-neutral `ProcessResult`/
//! `ProcessOptions` value boundary with direct argument execution and an
//! explicit terminal-observation path. It owns no long-lived child handles, PTY sessions,
//! AgentLoop routing, or runtime authority; those remain adapter/cutover work.

use std::io::{Read, Write};
use std::path::Path;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crate::contract::{
    PROCESS_ERROR_EXECUTION, PROCESS_ERROR_NONE, PROCESS_ERROR_NOT_FOUND,
    PROCESS_RETURN_EXECUTION_ERROR, PROCESS_RETURN_TIMEOUT, ProcessOptions, ProcessResult,
};
use crate::terminal_probe::TerminalObservation;

/// Version of the bounded one-shot process adapter contract.
pub const PROCESS_ADAPTER_CONTRACT_VERSION: u32 = 1;
/// Default retained byte limit for each captured output stream.
pub const PROCESS_DEFAULT_MAX_OUTPUT_BYTES: usize = 1 << 20;
/// Poll interval used while waiting for a bounded child deadline.
pub const PROCESS_POLL_INTERVAL_MS: u64 = 1;

/// Adapter construction failures that must be resolved before execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProcessAdapterError {
    /// A zero output limit cannot provide a useful bounded result.
    InvalidOutputLimit,
}

/// Configuration for one-shot process execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProcessAdapterConfig {
    /// Maximum retained bytes for stdout and stderr independently.
    pub max_output_bytes: usize,
    /// Poll interval used between child status checks.
    pub poll_interval: Duration,
}

impl ProcessAdapterConfig {
    /// Build the default bounded configuration with an explicit output limit.
    ///
    /// # Errors
    ///
    /// ProcessAdapterError when option bounds are invalid (non-positive limits).
    ///
    /// # Errors
    ///
    /// ProcessAdapterError when argv/shell requirements are unmet.
    pub fn new(max_output_bytes: usize) -> Result<Self, ProcessAdapterError> {
        if max_output_bytes == 0 {
            return Err(ProcessAdapterError::InvalidOutputLimit);
        }
        Ok(Self {
            max_output_bytes,
            poll_interval: Duration::from_millis(PROCESS_POLL_INTERVAL_MS),
        })
    }

    /// Return the standard bounded configuration.
    pub fn standard() -> Self {
        Self::new(PROCESS_DEFAULT_MAX_OUTPUT_BYTES).expect("default output limit is valid")
    }
}

/// One-shot process port implemented with bounded child capture.
#[derive(Debug, Clone)]
pub struct ProcessAdapter {
    config: ProcessAdapterConfig,
}

impl Default for ProcessAdapter {
    /// Create a process adapter with default limits.
    fn default() -> Self {
        Self {
            config: ProcessAdapterConfig::standard(),
        }
    }
}

impl ProcessAdapter {
    /// Construct an adapter with an explicit per-stream output limit.
    ///
    /// # Errors
    ///
    /// ProcessAdapterError forwarding config bound validation.
    pub fn new(max_output_bytes: usize) -> Result<Self, ProcessAdapterError> {
        Ok(Self {
            config: ProcessAdapterConfig::new(max_output_bytes)?,
        })
    }

    /// Construct an adapter from a validated configuration.
    pub const fn from_config(config: ProcessAdapterConfig) -> Self {
        Self { config }
    }

    /// Return the immutable adapter configuration.
    pub const fn config(&self) -> ProcessAdapterConfig {
        self.config
    }

    /// Run one command through an explicitly discovered terminal.
    ///
    /// The terminal observation supplies both the executable and invocation
    /// prefix. No platform default or shell switch is inferred here.
    pub fn run_terminal(
        &self,
        command_text: &str,
        terminal: &TerminalObservation,
        timeout: Duration,
        options: Option<&ProcessOptions>,
    ) -> ProcessResult {
        if let Err(error) = terminal.validate() {
            return failed_result(
                PROCESS_ERROR_EXECUTION,
                &format!("invalid terminal observation: {error:?}"),
            );
        }
        if let Some(error) = invalid_cwd(options) {
            return failed_result(PROCESS_ERROR_EXECUTION, &error);
        }
        if let Some(override_executable) = options.and_then(|value| value.executable.as_deref())
            && override_executable != terminal.executable
        {
            return failed_result(
                PROCESS_ERROR_EXECUTION,
                "terminal executable override differs from discovered terminal",
            );
        }
        self.run_args(&terminal.command_argv(command_text), timeout, options)
    }

    /// Run a pre-split argument list without shell interpretation.
    pub fn run_args(
        &self,
        args: &[String],
        timeout: Duration,
        options: Option<&ProcessOptions>,
    ) -> ProcessResult {
        if let Some(error) = invalid_cwd(options) {
            return failed_result(PROCESS_ERROR_EXECUTION, &error);
        }
        let Some(first) = args.first() else {
            return failed_result(PROCESS_ERROR_EXECUTION, "argument list is empty");
        };
        let executable = options
            .and_then(|options| options.executable.as_deref())
            .unwrap_or(first);
        let mut command = Command::new(executable);
        command.args(args.iter().skip(1));
        apply_options(&mut command, options);
        self.execute(
            command,
            timeout,
            options.and_then(|options| options.input_text.clone()),
        )
    }

    /// Execute a command with bounded capture and timeout.
    fn execute(
        &self,
        mut command: Command,
        timeout: Duration,
        input_text: Option<String>,
    ) -> ProcessResult {
        let stdin = if input_text.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        };
        let spawn_result = command
            .stdin(stdin)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();
        let mut child = match spawn_result {
            Ok(child) => child,
            Err(error) => {
                let error_kind = if error.kind() == std::io::ErrorKind::NotFound {
                    PROCESS_ERROR_NOT_FOUND
                } else {
                    PROCESS_ERROR_EXECUTION
                };
                return failed_result(error_kind, &error.to_string());
            }
        };

        let stdout_reader = child
            .stdout
            .take()
            .map(|reader| capture_stream(reader, self.config.max_output_bytes));
        let stderr_reader = child
            .stderr
            .take()
            .map(|reader| capture_stream(reader, self.config.max_output_bytes));
        let stdin_writer = input_text.and_then(|input| {
            child.stdin.take().map(|mut stdin| {
                thread::spawn(move || {
                    let _ = stdin.write_all(input.as_bytes());
                })
            })
        });

        let wait = wait_bounded(&mut child, timeout, self.config.poll_interval);
        if let Some(writer) = stdin_writer {
            let _ = writer.join();
        }
        let stdout = join_capture(stdout_reader);
        let stderr = join_capture(stderr_reader);
        result_from_wait(wait, stdout, stderr)
    }
}

/// Language-neutral process port surface used by future Rust/TS adapters.
pub trait ProcessPort: Send + Sync {
    /// Run pre-split arguments without shell interpretation.
    fn run_args(
        &self,
        args: &[String],
        timeout: Duration,
        options: Option<&ProcessOptions>,
    ) -> ProcessResult;
}

impl ProcessPort for ProcessAdapter {
    fn run_args(
        &self,
        args: &[String],
        timeout: Duration,
        options: Option<&ProcessOptions>,
    ) -> ProcessResult {
        Self::run_args(self, args, timeout, options)
    }
}

struct WaitResult {
    status: Option<ExitStatus>,
    timed_out: bool,
}

/// Wait for a child with a timeout, polling at a fixed interval.
fn wait_bounded(child: &mut Child, timeout: Duration, poll_interval: Duration) -> WaitResult {
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                return WaitResult {
                    status: Some(status),
                    timed_out: false,
                };
            }
            Ok(None) if timeout.is_zero() || started.elapsed() >= timeout => {
                let _ = child.kill();
                return WaitResult {
                    status: child.wait().ok(),
                    timed_out: true,
                };
            }
            Ok(None) => thread::sleep(poll_interval),
            Err(_) => {
                let _ = child.kill();
                return WaitResult {
                    status: child.wait().ok(),
                    timed_out: false,
                };
            }
        }
    }
}

/// Capture a stream into a bounded buffer on a background thread.
fn capture_stream<R>(mut reader: R, max_output_bytes: usize) -> JoinHandle<Vec<u8>>
where
    R: Read + Send + 'static,
{
    thread::spawn(move || {
        let mut retained = Vec::with_capacity(max_output_bytes.min(8192));
        let mut buffer = [0_u8; 8192];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(read) => {
                    let remaining = max_output_bytes.saturating_sub(retained.len());
                    retained.extend_from_slice(&buffer[..read.min(remaining)]);
                }
                Err(_) => break,
            }
        }
        retained
    })
}

/// Join a capture thread and decode its bytes as UTF-8.
fn join_capture(reader: Option<JoinHandle<Vec<u8>>>) -> String {
    reader
        .and_then(|reader| reader.join().ok())
        .map(|bytes| String::from_utf8_lossy(&bytes).into_owned())
        .unwrap_or_default()
}

/// Compose a process result from the wait outcome and captured output.
fn result_from_wait(wait: WaitResult, stdout: String, stderr: String) -> ProcessResult {
    if wait.timed_out {
        return ProcessResult {
            returncode: PROCESS_RETURN_TIMEOUT,
            stdout,
            stderr,
            timed_out: true,
            error_kind: PROCESS_ERROR_NONE.to_owned(),
        };
    }
    ProcessResult {
        returncode: wait
            .status
            .and_then(|status| status.code())
            .unwrap_or(PROCESS_RETURN_EXECUTION_ERROR),
        stdout,
        stderr,
        timed_out: false,
        error_kind: PROCESS_ERROR_NONE.to_owned(),
    }
}

/// Build a structured failure result.
fn failed_result(error_kind: &str, stderr: &str) -> ProcessResult {
    ProcessResult {
        returncode: PROCESS_RETURN_EXECUTION_ERROR,
        stdout: String::new(),
        stderr: stderr.to_owned(),
        timed_out: false,
        error_kind: error_kind.to_owned(),
    }
}

/// Apply caller options (cwd, env, limits) to a command.
fn apply_options(command: &mut Command, options: Option<&ProcessOptions>) {
    let Some(options) = options else {
        return;
    };
    if let Some(cwd) = &options.cwd {
        command.current_dir(cwd);
    }
    if let Some(env) = &options.env {
        command.env_clear();
        command.envs(env);
    }
}

/// Report an invalid working directory from options.
fn invalid_cwd(options: Option<&ProcessOptions>) -> Option<String> {
    let cwd = options.and_then(|options| options.cwd.as_deref())?;
    match Path::new(cwd).metadata() {
        Ok(metadata) if metadata.is_dir() => None,
        Ok(_) => Some(format!("working directory is not a directory: {cwd}")),
        Err(error) => Some(format!("working directory is unavailable: {error}")),
    }
}
