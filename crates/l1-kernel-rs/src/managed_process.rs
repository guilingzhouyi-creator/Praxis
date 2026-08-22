//! Rust-owned bounded process lifecycle candidate.
//!
//! This module owns short-lived child handles, generation-safe identity,
//! bounded output draining, cooperative stdin, wait/terminate, and explicit
//! reap. It does not implement PTYs, process groups, capability policy,
//! AgentLoop execution, or a production runtime entrypoint.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, ExitStatus, Stdio};
use std::sync::{Arc, Mutex, PoisonError, RwLock};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::contract::{
    PROCESS_ERROR_NONE, PROCESS_RETURN_EXECUTION_ERROR, ProcessOptions, ProcessResult,
};
use crate::process_adapter::ProcessAdapterConfig;
use crate::state_queue::ProcessHandleAllocator;
use crate::substrate::ProcessHandle;

/// Version of the bounded managed-process lifecycle contract.
pub const MANAGED_PROCESS_CONTRACT_VERSION: u32 = 1;

/// Terminal state retained after a managed child is observed or killed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ManagedProcessState {
    /// The child is still owned and may receive input or a stop request.
    Running,
    /// The child exited without an explicit stop request.
    Exited,
    /// The adapter sent a kill request and collected the child.
    Killed,
}

/// Public lifecycle snapshot that does not expose an OS child object.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ManagedProcessSnapshot {
    /// Generation-safe handle encoded at the wire boundary.
    pub handle: u64,
    /// Current lifecycle state.
    pub state: ManagedProcessState,
    /// Exit code when the process is terminal and the host provides one.
    pub returncode: Option<i32>,
}

/// Bounded lifecycle operation result for an observer wait.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ManagedWaitResult {
    /// The observer deadline elapsed; ownership remains with the book.
    Pending,
    /// The child reached a terminal state and its value result is available.
    Finished(ProcessResult),
}

/// Fail-closed errors from the managed process boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ManagedProcessError {
    /// The adapter configuration cannot retain output safely.
    InvalidOutputLimit,
    /// The command argument list has no executable.
    EmptyArguments,
    /// The requested working directory is invalid.
    InvalidCwd(String),
    /// The executable or shell cannot be found.
    NotFound(String),
    /// The host rejected process creation or lifecycle observation.
    Execution(String),
    /// No process slot is available.
    Capacity,
    /// The caller supplied a stale or unknown generation-safe handle.
    UnknownHandle,
    /// The operation requires a running child.
    NotRunning,
    /// The process did not terminate inside the explicit stop deadline.
    TerminationTimeout,
    /// The stdin stream has already been closed or was not retained.
    StdinClosed,
    /// The caller attempted to reap a live process.
    ProcessRunning,
}

/// Rust-owned managed child collection with bounded capacity.
pub struct ManagedProcessBook {
    config: ProcessAdapterConfig,
    allocator: Arc<ProcessHandleAllocator>,
    processes: RwLock<HashMap<ProcessHandle, Arc<ManagedProcess>>>,
}

struct ManagedProcess {
    inner: Mutex<ManagedProcessInner>,
}

struct ManagedProcessInner {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    stdout_reader: Option<JoinHandle<Vec<u8>>>,
    stderr_reader: Option<JoinHandle<Vec<u8>>>,
    state: ManagedProcessState,
    result: Option<ProcessResult>,
    kill_requested: bool,
}

impl ManagedProcessBook {
    /// Construct a bounded process book with an explicit slot limit.
    pub fn new(
        config: ProcessAdapterConfig,
        max_processes: u32,
    ) -> Result<Self, ManagedProcessError> {
        if config.max_output_bytes == 0 {
            return Err(ManagedProcessError::InvalidOutputLimit);
        }
        let allocator = ProcessHandleAllocator::new(max_processes)
            .map_err(|_| ManagedProcessError::Capacity)?;
        Ok(Self {
            config,
            allocator: Arc::new(allocator),
            processes: RwLock::new(HashMap::new()),
        })
    }

    /// Return the number of currently owned child handles.
    pub fn active_count(&self) -> usize {
        self.read_processes().len()
    }

    /// Spawn direct arguments without shell interpretation.
    pub fn spawn_args(
        &self,
        args: &[String],
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ManagedProcessError> {
        if let Some(error) = invalid_cwd(options) {
            return Err(ManagedProcessError::InvalidCwd(error));
        }
        let Some(first) = args.first() else {
            return Err(ManagedProcessError::EmptyArguments);
        };
        let executable = options
            .and_then(|value| value.executable.as_deref())
            .unwrap_or(first);
        let mut command = Command::new(executable);
        command.args(args.iter().skip(1));
        apply_options(&mut command, options);
        self.spawn_command(command)
    }

    /// Spawn one shell command through the platform shell.
    pub fn spawn_shell(
        &self,
        command_text: &str,
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ManagedProcessError> {
        if let Some(error) = invalid_cwd(options) {
            return Err(ManagedProcessError::InvalidCwd(error));
        }
        let executable = options
            .and_then(|value| value.executable.as_deref())
            .unwrap_or(default_shell());
        let mut command = Command::new(executable);
        command.arg(shell_switch()).arg(command_text);
        apply_options(&mut command, options);
        self.spawn_command(command)
    }

    /// Write one bounded caller-provided input frame to a running child.
    pub fn write_stdin(
        &self,
        handle: ProcessHandle,
        input: &[u8],
    ) -> Result<usize, ManagedProcessError> {
        let process = self.lookup(handle)?;
        let mut inner = process.inner.lock().unwrap_or_else(PoisonError::into_inner);
        if inner.state != ManagedProcessState::Running {
            return Err(ManagedProcessError::NotRunning);
        }
        let stdin = inner
            .stdin
            .as_mut()
            .ok_or(ManagedProcessError::StdinClosed)?;
        stdin
            .write_all(input)
            .map_err(|error| ManagedProcessError::Execution(error.to_string()))?;
        stdin
            .flush()
            .map_err(|error| ManagedProcessError::Execution(error.to_string()))?;
        Ok(input.len())
    }

    /// Close stdin while retaining ownership of the child handle.
    pub fn close_stdin(&self, handle: ProcessHandle) -> Result<(), ManagedProcessError> {
        let process = self.lookup(handle)?;
        let mut inner = process.inner.lock().unwrap_or_else(PoisonError::into_inner);
        if inner.state != ManagedProcessState::Running {
            return Err(ManagedProcessError::NotRunning);
        }
        inner.stdin.take();
        Ok(())
    }

    /// Observe a child for at most `timeout` without changing ownership.
    pub fn wait(
        &self,
        handle: ProcessHandle,
        timeout: Duration,
    ) -> Result<ManagedWaitResult, ManagedProcessError> {
        let process = self.lookup(handle)?;
        let deadline = Instant::now()
            .checked_add(timeout)
            .unwrap_or_else(Instant::now);
        loop {
            {
                let mut inner = process.inner.lock().unwrap_or_else(PoisonError::into_inner);
                if inner.state != ManagedProcessState::Running {
                    return Ok(ManagedWaitResult::Finished(
                        inner.result.clone().unwrap_or_default(),
                    ));
                }
                if observe_exit(&mut inner)? {
                    return Ok(ManagedWaitResult::Finished(
                        inner.result.clone().unwrap_or_default(),
                    ));
                }
            }
            if timeout.is_zero() || Instant::now() >= deadline {
                return Ok(ManagedWaitResult::Pending);
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            thread::sleep(self.config.poll_interval.min(remaining));
        }
    }

    /// Kill a running child and collect it within the explicit deadline.
    pub fn terminate(
        &self,
        handle: ProcessHandle,
        timeout: Duration,
    ) -> Result<ProcessResult, ManagedProcessError> {
        let process = self.lookup(handle)?;
        let mut inner = process.inner.lock().unwrap_or_else(PoisonError::into_inner);
        if inner.state != ManagedProcessState::Running {
            return Ok(inner.result.clone().unwrap_or_default());
        }
        let (status, killed) = {
            let observed = inner
                .child
                .as_mut()
                .ok_or_else(|| {
                    ManagedProcessError::Execution("child handle is missing".to_owned())
                })?
                .try_wait()
                .map_err(|error| ManagedProcessError::Execution(error.to_string()))?;
            if let Some(status) = observed {
                (Some(status), false)
            } else {
                inner.kill_requested = true;
                let child = inner.child.as_mut().ok_or_else(|| {
                    ManagedProcessError::Execution("child handle is missing".to_owned())
                })?;
                child
                    .kill()
                    .map_err(|error| ManagedProcessError::Execution(error.to_string()))?;
                (wait_child(child, timeout, self.config.poll_interval)?, true)
            }
        };
        let Some(status) = status else {
            return Err(ManagedProcessError::TerminationTimeout);
        };
        finish(&mut inner, Some(status), killed);
        Ok(inner.result.clone().unwrap_or_default())
    }

    /// Return a public snapshot without exposing a `Child` or pipe.
    pub fn snapshot(
        &self,
        handle: ProcessHandle,
    ) -> Result<ManagedProcessSnapshot, ManagedProcessError> {
        let process = self.lookup(handle)?;
        let inner = process.inner.lock().unwrap_or_else(PoisonError::into_inner);
        Ok(ManagedProcessSnapshot {
            handle: handle.raw(),
            state: inner.state,
            returncode: inner.result.as_ref().map(|result| result.returncode),
        })
    }

    /// Reap a terminal child and release its generation-safe slot.
    pub fn reap(&self, handle: ProcessHandle) -> Result<ProcessResult, ManagedProcessError> {
        let mut processes = self.write_processes();
        let process = processes
            .get(&handle)
            .cloned()
            .ok_or(ManagedProcessError::UnknownHandle)?;
        let inner = process.inner.lock().unwrap_or_else(PoisonError::into_inner);
        if inner.state == ManagedProcessState::Running {
            return Err(ManagedProcessError::ProcessRunning);
        }
        let result = inner.result.clone().unwrap_or_default();
        self.allocator
            .release(handle)
            .map_err(|error| ManagedProcessError::Execution(error.to_owned()))?;
        processes.remove(&handle);
        Ok(result)
    }

    fn spawn_command(&self, mut command: Command) -> Result<ProcessHandle, ManagedProcessError> {
        let handle = self
            .allocator
            .allocate()
            .map_err(|_| ManagedProcessError::Capacity)?;
        let mut child = match command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                let _ = self.allocator.release(handle);
                return Err(map_spawn_error(error));
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
        let stdin = child.stdin.take();
        let process = Arc::new(ManagedProcess {
            inner: Mutex::new(ManagedProcessInner {
                child: Some(child),
                stdin,
                stdout_reader,
                stderr_reader,
                state: ManagedProcessState::Running,
                result: None,
                kill_requested: false,
            }),
        });
        self.write_processes().insert(handle, process);
        Ok(handle)
    }

    fn lookup(&self, handle: ProcessHandle) -> Result<Arc<ManagedProcess>, ManagedProcessError> {
        self.read_processes()
            .get(&handle)
            .cloned()
            .ok_or(ManagedProcessError::UnknownHandle)
    }

    fn read_processes(
        &self,
    ) -> std::sync::RwLockReadGuard<'_, HashMap<ProcessHandle, Arc<ManagedProcess>>> {
        self.processes
            .read()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn write_processes(
        &self,
    ) -> std::sync::RwLockWriteGuard<'_, HashMap<ProcessHandle, Arc<ManagedProcess>>> {
        self.processes
            .write()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl Drop for ManagedProcessBook {
    fn drop(&mut self) {
        let processes = std::mem::take(
            self.processes
                .get_mut()
                .unwrap_or_else(PoisonError::into_inner),
        );
        for (handle, process) in processes {
            let mut inner = process.inner.lock().unwrap_or_else(PoisonError::into_inner);
            if inner.state == ManagedProcessState::Running {
                inner.kill_requested = true;
                if let Some(child) = inner.child.as_mut() {
                    let _ = child.kill();
                    let status = child.wait().ok();
                    finish(&mut inner, status, true);
                }
            }
            let _ = self.allocator.release(handle);
        }
    }
}

fn observe_exit(inner: &mut ManagedProcessInner) -> Result<bool, ManagedProcessError> {
    let observed = inner
        .child
        .as_mut()
        .ok_or_else(|| ManagedProcessError::Execution("child handle is missing".to_owned()))?
        .try_wait()
        .map_err(|error| ManagedProcessError::Execution(error.to_string()))?;
    if let Some(status) = observed {
        finish(inner, Some(status), false);
        Ok(true)
    } else {
        Ok(false)
    }
}

fn wait_child(
    child: &mut Child,
    timeout: Duration,
    poll_interval: Duration,
) -> Result<Option<ExitStatus>, ManagedProcessError> {
    let deadline = Instant::now()
        .checked_add(timeout)
        .unwrap_or_else(Instant::now);
    loop {
        let status = child
            .try_wait()
            .map_err(|error| ManagedProcessError::Execution(error.to_string()))?;
        if status.is_some() {
            return Ok(status);
        }
        if timeout.is_zero() || Instant::now() >= deadline {
            return Ok(None);
        }
        thread::sleep(poll_interval.min(deadline.saturating_duration_since(Instant::now())));
    }
}

fn finish(inner: &mut ManagedProcessInner, status: Option<ExitStatus>, killed: bool) {
    inner.child.take();
    inner.stdin.take();
    let stdout = join_capture(inner.stdout_reader.take());
    let stderr = join_capture(inner.stderr_reader.take());
    let returncode = status
        .and_then(|value| value.code())
        .unwrap_or(PROCESS_RETURN_EXECUTION_ERROR);
    inner.result = Some(ProcessResult {
        returncode,
        stdout,
        stderr,
        timed_out: false,
        error_kind: PROCESS_ERROR_NONE.to_owned(),
    });
    inner.state = if killed || inner.kill_requested {
        ManagedProcessState::Killed
    } else {
        ManagedProcessState::Exited
    };
}

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

fn join_capture(reader: Option<JoinHandle<Vec<u8>>>) -> String {
    reader
        .and_then(|value| value.join().ok())
        .map(|bytes| String::from_utf8_lossy(&bytes).into_owned())
        .unwrap_or_default()
}

fn map_spawn_error(error: std::io::Error) -> ManagedProcessError {
    if error.kind() == std::io::ErrorKind::NotFound {
        ManagedProcessError::NotFound(error.to_string())
    } else {
        ManagedProcessError::Execution(error.to_string())
    }
}

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

fn invalid_cwd(options: Option<&ProcessOptions>) -> Option<String> {
    let cwd = options.and_then(|value| value.cwd.as_deref())?;
    match Path::new(cwd).metadata() {
        Ok(metadata) if metadata.is_dir() => None,
        Ok(_) => Some(format!("working directory is not a directory: {cwd}")),
        Err(error) => Some(format!("working directory is unavailable: {error}")),
    }
}

#[cfg(unix)]
fn default_shell() -> &'static str {
    "/bin/sh"
}

#[cfg(windows)]
fn default_shell() -> &'static str {
    "cmd.exe"
}

#[cfg(unix)]
fn shell_switch() -> &'static str {
    "-c"
}

#[cfg(windows)]
fn shell_switch() -> &'static str {
    "/C"
}
