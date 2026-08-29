//! Rust-native OS lifecycle coordination for the clean-break kernel.
//!
//! The coordinator owns only lifecycle orchestration: callers inject boot,
//! shutdown, reset, and watchdog callbacks, while the kernel provides
//! serialized state transitions, bounded callback waits, restart sequencing,
//! and a stoppable watchdog loop. It does not discover Python/L3 services,
//! shells, providers, terminals, or platform processes.

use std::collections::BTreeMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{
    Arc, Condvar, MutexGuard, OnceLock, PoisonError,
    mpsc::{self, RecvTimeoutError},
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::watchdog::WatchdogReport;

/// Version of the Rust OS coordinator contract.
pub const OS_CONTRACT_VERSION: u32 = 1;
/// Default bounded wait used for shutdown hooks and reset callbacks.
pub const DEFAULT_SHUTDOWN_TIMEOUT_MS: u64 = 5_000;
/// Default interval for an explicitly enabled watchdog loop.
pub const DEFAULT_WATCHDOG_INTERVAL_MS: u64 = 60_000;

/// High-level lifecycle state of the Rust OS coordinator.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum OsState {
    /// No OS callbacks are currently active.
    Down,
    /// The boot callback is executing.
    Starting,
    /// Boot completed successfully.
    Running,
    /// Shutdown callbacks are draining.
    Stopping,
    /// Boot or a lifecycle callback failed.
    Crashed,
}

impl OsState {
    /// Return the stable uppercase wire spelling used by the Python facade.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Down => "DOWN",
            Self::Starting => "STARTING",
            Self::Running => "RUNNING",
            Self::Stopping => "STOPPING",
            Self::Crashed => "CRASHED",
        }
    }
}

/// Structured lifecycle failures at the OS coordination boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OsError {
    /// A second boot was requested while boot or service execution is active.
    AlreadyActive(OsState),
    /// A boot callback has not been injected.
    NoBootHandler,
    /// An injected callback returned an application error or panicked.
    HandlerFailed { stage: String, message: String },
    /// A watchdog interval of zero cannot produce a bounded loop.
    InvalidWatchdogInterval,
    /// A watchdog observation callback returned an error or panicked.
    WatchdogFailed(String),
}

impl std::fmt::Display for OsError {
    /// Render a stable human-readable lifecycle failure.
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::AlreadyActive(state) => {
                write!(formatter, "OS is already {}", state.as_str().to_lowercase())
            }
            Self::NoBootHandler => formatter.write_str("no boot handler registered"),
            Self::HandlerFailed { stage, message } => {
                write!(formatter, "{stage} handler failed: {message}")
            }
            Self::InvalidWatchdogInterval => {
                formatter.write_str("watchdog interval must be greater than zero")
            }
            Self::WatchdogFailed(message) => {
                write!(formatter, "watchdog observation failed: {message}")
            }
        }
    }
}

impl std::error::Error for OsError {}

/// Stable report returned after a successful boot callback.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OsBootReport {
    /// OS coordinator contract version.
    pub contract_version: u32,
    /// Whether the callback completed successfully.
    pub success: bool,
    /// State after callback completion.
    pub state: OsState,
    /// Number of agents reported by the injected callback, if present.
    pub agent_count: u64,
    /// Callback elapsed time in milliseconds.
    pub elapsed_ms: u64,
    /// Opaque callback result retained for the host adapter.
    pub data: Value,
}

/// Stable report returned after shutdown and reset callbacks have been run.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OsShutdownReport {
    /// OS coordinator contract version.
    pub contract_version: u32,
    /// Shutdown always reaches a terminal coordinator state; callback
    /// timeouts and errors are retained in `results`.
    pub success: bool,
    /// State after the shutdown sweep.
    pub state: OsState,
    /// Time spent in the prior boot interval, in milliseconds.
    pub uptime_ms: u64,
    /// Per-hook, persistence, and reset outcomes in execution order.
    pub results: BTreeMap<String, Value>,
}

/// Read-only status snapshot for monitoring and host adapters.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OsStatus {
    /// Current coordinator state.
    pub state: OsState,
    /// Uptime while running, otherwise zero.
    pub uptime_ms: u64,
    /// Whether the watchdog loop is currently enabled.
    pub watchdog: bool,
    /// Number of registered shutdown hooks.
    pub hooks: usize,
    /// Number of failed watchdog observations.
    #[serde(default)]
    pub watchdog_errors: u64,
}

/// Boot callback supplied by the host/application boundary.
pub type BootHandler = Arc<dyn Fn(Option<Value>) -> Result<Value, String> + Send + Sync>;
/// Shutdown/persistence callback supplied by the host/application boundary.
pub type ShutdownHandler = Arc<dyn Fn() -> Result<Value, String> + Send + Sync>;
/// Reset callback for a host-owned terminal or Cell registry.
pub type ResetHandler = Arc<dyn Fn() -> Result<(), String> + Send + Sync>;
/// One bounded shutdown hook.
pub type ShutdownHook = Arc<dyn Fn() -> Result<(), String> + Send + Sync>;
/// Watchdog observation callback returning a value-only report.
pub type WatchdogHandler = Arc<dyn Fn() -> Result<WatchdogReport, String> + Send + Sync>;

struct WatchdogControl {
    stop: Arc<(std::sync::Mutex<bool>, Condvar)>,
    thread: Option<JoinHandle<()>>,
}

struct OsInner {
    state: OsState,
    started_at: Option<Instant>,
    boot_handler: Option<BootHandler>,
    shutdown_handler: Option<ShutdownHandler>,
    terminal_reset_handler: Option<ResetHandler>,
    cell_reset_handler: Option<ResetHandler>,
    shutdown_hooks: Vec<ShutdownHook>,
    watchdog_handler: Option<WatchdogHandler>,
    watchdog: Option<WatchdogControl>,
    last_watchdog: Option<WatchdogReport>,
    watchdog_errors: u64,
}

impl Default for OsInner {
    fn default() -> Self {
        Self {
            state: OsState::Down,
            started_at: None,
            boot_handler: None,
            shutdown_handler: None,
            terminal_reset_handler: None,
            cell_reset_handler: None,
            shutdown_hooks: Vec::new(),
            watchdog_handler: None,
            watchdog: None,
            last_watchdog: None,
            watchdog_errors: 0,
        }
    }
}

/// Thread-safe lifecycle coordinator for the clean-break Rust kernel.
#[derive(Clone)]
pub struct OsCoordinator {
    inner: Arc<std::sync::Mutex<OsInner>>,
    operation: Arc<std::sync::Mutex<()>>,
}

impl OsCoordinator {
    /// Create a coordinator in the `DOWN` state with no injected callbacks.
    pub fn new() -> Self {
        Self {
            inner: Arc::new(std::sync::Mutex::new(OsInner::default())),
            operation: Arc::new(std::sync::Mutex::new(())),
        }
    }

    /// Register the host boot callback.
    pub fn register_boot_handler<F>(&self, handler: F)
    where
        F: Fn(Option<Value>) -> Result<Value, String> + Send + Sync + 'static,
    {
        self.lock_inner().boot_handler = Some(Arc::new(handler));
    }

    /// Register the host shutdown/persistence callback.
    pub fn register_shutdown_handler<F>(&self, handler: F)
    where
        F: Fn() -> Result<Value, String> + Send + Sync + 'static,
    {
        self.lock_inner().shutdown_handler = Some(Arc::new(handler));
    }

    /// Register a host terminal reset callback.
    pub fn register_terminal_reset<F>(&self, handler: F)
    where
        F: Fn() -> Result<(), String> + Send + Sync + 'static,
    {
        self.lock_inner().terminal_reset_handler = Some(Arc::new(handler));
    }

    /// Register a host Cell reset callback.
    pub fn register_cell_reset<F>(&self, handler: F)
    where
        F: Fn() -> Result<(), String> + Send + Sync + 'static,
    {
        self.lock_inner().cell_reset_handler = Some(Arc::new(handler));
    }

    /// Register one callback executed in insertion order during shutdown.
    pub fn on_shutdown<F>(&self, hook: F)
    where
        F: Fn() -> Result<(), String> + Send + Sync + 'static,
    {
        self.lock_inner().shutdown_hooks.push(Arc::new(hook));
    }

    /// Register the value-only watchdog observer used by `watchdog_start`.
    pub fn register_watchdog_handler<F>(&self, handler: F)
    where
        F: Fn() -> Result<WatchdogReport, String> + Send + Sync + 'static,
    {
        self.lock_inner().watchdog_handler = Some(Arc::new(handler));
    }

    /// Boot the injected host boundary and move `STARTING` to `RUNNING`.
    ///
    /// # Errors
    ///
    /// Returns a structured error when the coordinator is already active,
    /// the boot handler is absent, or the callback fails/panics. Failures
    /// leave the coordinator in `CRASHED`.
    pub fn boot(&self, config: Option<Value>) -> Result<OsBootReport, OsError> {
        {
            let inner = self.lock_inner();
            if matches!(
                inner.state,
                OsState::Running | OsState::Starting | OsState::Stopping
            ) {
                return Err(OsError::AlreadyActive(inner.state));
            }
        }
        // Keep boot and shutdown callbacks from interleaving their terminal
        // state transitions. The fast state check above still lets a second
        // boot fail immediately while the first callback is running.
        let _operation = self.lock_operation();
        let started = Instant::now();
        let handler = {
            let mut inner = self.lock_inner();
            if matches!(
                inner.state,
                OsState::Running | OsState::Starting | OsState::Stopping
            ) {
                return Err(OsError::AlreadyActive(inner.state));
            }
            inner.state = OsState::Starting;
            inner.started_at = Some(started);
            inner.boot_handler.clone()
        };
        let Some(handler) = handler else {
            self.lock_inner().state = OsState::Crashed;
            return Err(OsError::NoBootHandler);
        };

        let result = catch_unwind(AssertUnwindSafe(|| handler(config)));
        let data = match result {
            Ok(Ok(data)) => data,
            Ok(Err(message)) => {
                self.lock_inner().state = OsState::Crashed;
                return Err(OsError::HandlerFailed {
                    stage: "boot".to_owned(),
                    message,
                });
            }
            Err(_) => {
                self.lock_inner().state = OsState::Crashed;
                return Err(OsError::HandlerFailed {
                    stage: "boot".to_owned(),
                    message: "callback panicked".to_owned(),
                });
            }
        };
        {
            let mut inner = self.lock_inner();
            inner.state = OsState::Running;
        }
        Ok(OsBootReport {
            contract_version: OS_CONTRACT_VERSION,
            success: true,
            state: OsState::Running,
            agent_count: data
                .get("agent_count")
                .and_then(Value::as_u64)
                .unwrap_or_default(),
            elapsed_ms: started.elapsed().as_millis().try_into().unwrap_or(u64::MAX),
            data,
        })
    }

    /// Gracefully run hooks, persistence, and reset callbacks.
    ///
    /// Each callback runs on a detached bounded-wait thread, matching the
    /// Python coordinator's timeout semantics without pretending a running
    /// host callback can be forcibly interrupted.
    pub fn shutdown(&self, timeout: Option<Duration>) -> OsShutdownReport {
        let timeout = timeout.unwrap_or_else(|| Duration::from_millis(DEFAULT_SHUTDOWN_TIMEOUT_MS));
        if self.lock_inner().state == OsState::Stopping {
            return OsShutdownReport {
                contract_version: OS_CONTRACT_VERSION,
                success: true,
                state: OsState::Stopping,
                uptime_ms: 0,
                results: BTreeMap::from([("reason".to_owned(), json!("already stopping"))]),
            };
        }
        // A boot callback may still be running. Waiting here serializes its
        // final state publication with shutdown instead of allowing a late
        // boot success to resurrect a drained coordinator.
        let _operation = self.lock_operation();
        let boot_started = {
            let mut inner = self.lock_inner();
            if inner.state == OsState::Stopping {
                return OsShutdownReport {
                    contract_version: OS_CONTRACT_VERSION,
                    success: true,
                    state: OsState::Stopping,
                    uptime_ms: 0,
                    results: BTreeMap::from([("reason".to_owned(), json!("already stopping"))]),
                };
            }
            inner.state = OsState::Stopping;
            inner.started_at
        };

        let mut results = BTreeMap::new();
        let hooks = self.lock_inner().shutdown_hooks.clone();
        for (index, hook) in hooks.into_iter().enumerate() {
            results.insert(
                format!("hook_{index}"),
                callback_outcome(run_with_timeout(move || hook(), timeout)),
            );
        }

        let shutdown_handler = self.lock_inner().shutdown_handler.clone();
        match shutdown_handler {
            Some(handler) => match run_with_timeout(move || handler(), timeout) {
                TimedOutcome::Ok(Ok(value)) => {
                    let value = value.get("results").cloned().unwrap_or(value);
                    results.insert("memories".to_owned(), value);
                }
                TimedOutcome::Ok(Err(message)) => {
                    results.insert("memories".to_owned(), json!(format!("error: {message}")));
                }
                TimedOutcome::Timeout => {
                    results.insert("memories".to_owned(), json!("timeout"));
                }
                TimedOutcome::Panic => {
                    results.insert("memories".to_owned(), json!("error: callback panicked"));
                }
            },
            None => {
                results.insert("memories".to_owned(), json!({}));
            }
        }

        self.watchdog_stop();

        let terminal_reset = self.lock_inner().terminal_reset_handler.clone();
        results.insert(
            "reset_term".to_owned(),
            reset_outcome(
                terminal_reset.map(|handler| run_with_timeout(move || handler(), timeout)),
            ),
        );
        let cell_reset = self.lock_inner().cell_reset_handler.clone();
        results.insert(
            "reset_cell".to_owned(),
            reset_outcome(cell_reset.map(|handler| run_with_timeout(move || handler(), timeout))),
        );
        results.insert("reset".to_owned(), json!("ok"));

        let uptime_ms = boot_started
            .map(|started| started.elapsed().as_millis().try_into().unwrap_or(u64::MAX))
            .unwrap_or_default();
        {
            let mut inner = self.lock_inner();
            inner.state = OsState::Down;
            inner.started_at = None;
        }
        OsShutdownReport {
            contract_version: OS_CONTRACT_VERSION,
            success: true,
            state: OsState::Down,
            uptime_ms,
            results,
        }
    }

    /// Shut down and then boot again, preserving injected callbacks.
    pub fn restart(
        &self,
        config: Option<Value>,
        timeout: Option<Duration>,
    ) -> Result<(OsShutdownReport, OsBootReport), OsError> {
        let shutdown = self.shutdown(timeout);
        let boot = self.boot(config)?;
        Ok((shutdown, boot))
    }

    /// Start a stoppable background watchdog loop.
    ///
    /// An absent observation callback is permitted so hosts can enable the
    /// loop before wiring a provider. The loop remains side-effect free until
    /// a callback is registered.
    pub fn watchdog_start(&self, interval: Duration) -> Result<(), OsError> {
        if interval.is_zero() {
            return Err(OsError::InvalidWatchdogInterval);
        }
        {
            let mut state = self.lock_inner();
            if state.watchdog.is_some() {
                return Ok(());
            }
            let stop = Arc::new((std::sync::Mutex::new(false), Condvar::new()));
            let thread_stop = Arc::clone(&stop);
            let inner = Arc::clone(&self.inner);
            let thread = thread::Builder::new()
                .name("praxis-rust-watchdog".to_owned())
                .spawn(move || watchdog_loop(thread_stop, inner, interval))
                .map_err(|error| OsError::WatchdogFailed(error.to_string()))?;
            state.watchdog = Some(WatchdogControl {
                stop: Arc::clone(&stop),
                thread: Some(thread),
            });
        }
        Ok(())
    }

    /// Stop the watchdog loop and join it without waiting out its interval.
    pub fn watchdog_stop(&self) {
        let control = self.lock_inner().watchdog.take();
        let Some(mut control) = control else {
            return;
        };
        {
            let (flag, wake) = &*control.stop;
            *flag.lock().unwrap_or_else(PoisonError::into_inner) = true;
            wake.notify_all();
        }
        if let Some(thread) = control.thread.take() {
            let _ = thread.join();
        }
    }

    /// Run one explicit watchdog observation immediately.
    ///
    /// # Errors
    ///
    /// Returns `Ok(None)` when no observer is wired; callback failures are
    /// counted and returned as structured `WatchdogFailed` errors.
    pub fn watchdog_tick(&self) -> Result<Option<WatchdogReport>, OsError> {
        let handler = self.lock_inner().watchdog_handler.clone();
        let Some(handler) = handler else {
            return Ok(None);
        };
        match catch_unwind(AssertUnwindSafe(|| handler())) {
            Ok(Ok(report)) => {
                self.lock_inner().last_watchdog = Some(report.clone());
                Ok(Some(report))
            }
            Ok(Err(message)) => {
                let mut inner = self.lock_inner();
                inner.watchdog_errors = inner.watchdog_errors.saturating_add(1);
                Err(OsError::WatchdogFailed(message))
            }
            Err(_) => {
                let mut inner = self.lock_inner();
                inner.watchdog_errors = inner.watchdog_errors.saturating_add(1);
                Err(OsError::WatchdogFailed("callback panicked".to_owned()))
            }
        }
    }

    /// Return the current lifecycle, uptime, watchdog, and hook status.
    pub fn status(&self) -> OsStatus {
        let inner = self.lock_inner();
        OsStatus {
            state: inner.state,
            uptime_ms: if inner.state == OsState::Running {
                inner
                    .started_at
                    .map(|started| started.elapsed().as_millis().try_into().unwrap_or(u64::MAX))
                    .unwrap_or_default()
            } else {
                0
            },
            watchdog: inner.watchdog.is_some(),
            hooks: inner.shutdown_hooks.len(),
            watchdog_errors: inner.watchdog_errors,
        }
    }

    /// Return the latest value-only watchdog report, if one was observed.
    pub fn last_watchdog(&self) -> Option<WatchdogReport> {
        self.lock_inner().last_watchdog.clone()
    }

    fn lock_inner(&self) -> MutexGuard<'_, OsInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_operation(&self) -> MutexGuard<'_, ()> {
        self.operation
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for OsCoordinator {
    fn default() -> Self {
        Self::new()
    }
}

/// Internal result preserving timeout and panic as distinct observable outcomes.
enum TimedOutcome<T> {
    Ok(T),
    Timeout,
    Panic,
}

/// Run one callback on a detached thread and wait for at most `timeout`.
fn run_with_timeout<F, T>(callback: F, timeout: Duration) -> TimedOutcome<T>
where
    F: FnOnce() -> T + Send + 'static,
    T: Send + 'static,
{
    let (sender, receiver) = mpsc::channel();
    let spawned = thread::Builder::new()
        .name("praxis-rust-os-callback".to_owned())
        .spawn(move || {
            let result = catch_unwind(AssertUnwindSafe(callback));
            let _ = sender.send(match result {
                Ok(value) => TimedOutcome::Ok(value),
                Err(_) => TimedOutcome::Panic,
            });
        });
    if spawned.is_err() {
        return TimedOutcome::Panic;
    }
    match receiver.recv_timeout(timeout) {
        Ok(result) => result,
        Err(RecvTimeoutError::Timeout) | Err(RecvTimeoutError::Disconnected) => {
            TimedOutcome::Timeout
        }
    }
}

/// Render a hook callback result in the shutdown report.
fn callback_outcome(outcome: TimedOutcome<Result<(), String>>) -> Value {
    match outcome {
        TimedOutcome::Ok(Ok(())) => json!("ok"),
        TimedOutcome::Ok(Err(message)) => json!(format!("error: {message}")),
        TimedOutcome::Timeout => json!("timeout"),
        TimedOutcome::Panic => json!("error: callback panicked"),
    }
}

/// Render an optional terminal/Cell reset callback result.
fn reset_outcome(outcome: Option<TimedOutcome<Result<(), String>>>) -> Value {
    match outcome {
        None => json!("skip"),
        Some(TimedOutcome::Ok(Ok(()))) => json!("ok"),
        Some(TimedOutcome::Ok(Err(message))) => json!(format!("error: {message}")),
        Some(TimedOutcome::Timeout) => json!("timeout"),
        Some(TimedOutcome::Panic) => json!("error: callback panicked"),
    }
}

/// Wait for the interval or a stop notification, then run host observations.
fn watchdog_loop(
    stop: Arc<(std::sync::Mutex<bool>, Condvar)>,
    inner: Arc<std::sync::Mutex<OsInner>>,
    interval: Duration,
) {
    loop {
        let stopped = {
            let (flag, wake) = &*stop;
            let guard = flag.lock().unwrap_or_else(PoisonError::into_inner);
            let (guard, _) = wake
                .wait_timeout(guard, interval)
                .unwrap_or_else(|error| error.into_inner());
            *guard
        };
        if stopped {
            return;
        }
        let handler = inner
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .watchdog_handler
            .clone();
        let Some(handler) = handler else {
            continue;
        };
        let result = catch_unwind(AssertUnwindSafe(|| handler()));
        let mut state = inner.lock().unwrap_or_else(PoisonError::into_inner);
        match result {
            Ok(Ok(report)) => state.last_watchdog = Some(report),
            Ok(Err(_)) | Err(_) => {
                state.watchdog_errors = state.watchdog_errors.saturating_add(1);
            }
        }
    }
}

static GLOBAL_OS: OnceLock<std::sync::Mutex<Option<Arc<OsCoordinator>>>> = OnceLock::new();

/// Return the process-wide Rust OS coordinator.
pub fn get_os() -> Arc<OsCoordinator> {
    let slot = GLOBAL_OS.get_or_init(|| std::sync::Mutex::new(None));
    let mut guard = slot.lock().unwrap_or_else(PoisonError::into_inner);
    Arc::clone(guard.get_or_insert_with(|| Arc::new(OsCoordinator::new())))
}

/// Reset the process-wide coordinator and stop any active watchdog thread.
pub fn reset_os() {
    let slot = GLOBAL_OS.get_or_init(|| std::sync::Mutex::new(None));
    let old = slot.lock().unwrap_or_else(PoisonError::into_inner).take();
    if let Some(old) = old {
        old.watchdog_stop();
    }
}
