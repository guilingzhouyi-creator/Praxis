//! Rust-owned execution host candidate for the clean-break kernel.
//!
//! This module composes the validated assembly metadata, lifecycle FSM,
//! generation-safe process handles, and bounded worker pool into one explicit
//! execution boundary. It accepts already-bound Rust closures only; Python,
//! PTY, AgentLoop, prompt, tool, provider, and frontend policy remain outside
//! this candidate until cutover and recovery gates are complete.

use std::collections::BTreeMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{
    Arc, Mutex as StdMutex, MutexGuard, PoisonError, RwLock, RwLockReadGuard, TryLockError,
};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::agent_loop::AgentLoopBook;
use crate::assembly::{AssemblyError, AssemblySpec, KernelAssembly};
use crate::capability::CapabilityAuthority;
use crate::contract::{CapabilityRequest, CapabilityResult};
use crate::execution_store::{ExecutionStore, ExecutionStoreDocument, ExecutionStoreError};
use crate::gatechain::{GateChain, GateDecision, GateRequest};
use crate::lifecycle::{LifecycleRegistry, LifecycleState};
use crate::recovery::{RecoveryAction, RecoveryDecision, RecoveryTrigger};
use crate::scheduler::{KernelScheduler, SchedulerConfig, SchedulerError};
use crate::session::SessionBook;
use crate::state_store::{StateStore, StateStoreError};
use crate::substrate::ProcessHandle;
use crate::terminal::TerminalBook;
use crate::worker::{TaskFn, TaskHandle, TaskHandleError, WorkerConfig, WorkerPool};

/// Runtime-owned task lifecycle, independent of worker implementation details.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeTaskState {
    /// Accepted but not started by a worker.
    Ready,
    /// Currently executing the submitted closure.
    Running,
    /// Closure returned a value successfully.
    Succeeded,
    /// Closure returned an application error or the worker caught a panic.
    Failed,
    /// Cancellation won before execution began.
    Cancelled,
    /// The task deadline elapsed before completion.
    TimedOut,
}

impl RuntimeTaskState {
    fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Succeeded | Self::Failed | Self::Cancelled | Self::TimedOut
        )
    }
}

/// Explicit limits for the runtime execution host.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RuntimeConfig {
    /// Maximum concurrently allocated process handles.
    /// Maximum concurrently registered processes.
    pub max_processes: u32,
    /// Number of independent scheduler state shards.
    /// State-map shard count (power-of-two recommended).
    pub shard_count: u32,
    /// Worker-pool sizing and bounded queue limits.
    /// Worker-pool sizing configuration.
    pub workers: WorkerConfig,
}

impl RuntimeConfig {
    /// Build a runtime configuration from explicit deployment values.
    pub const fn new(max_processes: u32, shard_count: u32, workers: WorkerConfig) -> Self {
        Self {
            max_processes,
            shard_count,
            workers,
        }
    }
}

/// Stable runtime snapshot exposed to adapters and evidence collectors.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeSnapshot {
    /// Current lifecycle phase.
    /// Current kernel lifecycle state.
    pub lifecycle: LifecycleState,
    /// Number of allocated, unreaped task handles.
    /// Live tasks tracked by this runtime.
    pub task_count: usize,
    /// Number of terminal tasks still awaiting reap.
    /// Tasks in terminal (finished) state.
    pub terminal_tasks: usize,
    /// Worker-pool metrics at the same observation point.
    /// Worker-pool statistics payload.
    pub worker_stats: BTreeMap<String, Value>,
}

/// Result of one bounded caller-driven runtime reaper sweep.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeReapReport {
    /// Number of task handles selected within the requested budget.
    /// Children observed by the last reaper sweep.
    pub inspected: u64,
    /// Number of terminal tasks whose scheduler slots were released.
    /// Children reaped by the last sweep.
    pub reaped: u64,
    /// Number of selected tasks that were still ready or running.
    /// Children still running at sweep time.
    pub pending: u64,
    /// Number of handles removed concurrently before this sweep could reap them.
    /// Sweep observations that could not be made.
    pub unavailable: u64,
    /// Number of terminal tasks whose scheduler slot could not be released.
    /// Errors encountered during the sweep.
    pub errors: u64,
}

/// Fail-closed errors at the runtime host boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeError {
    /// Declarative assembly rejected the host specification.
    Assembly(AssemblyError),
    /// The process-handle capacity is exhausted.
    ProcessCapacity,
    /// The worker pool could not be created.
    WorkerConfig(&'static str),
    /// The worker pool rejected a strict all-or-none batch.
    WorkerRejected(String),
    /// The Rust-owned session book could not be initialized or restored.
    Session(String),
    /// The combined execution checkpoint could not be opened or restored.
    ExecutionStore(String),
    /// The scheduler candidate rejected its configuration or transition.
    Scheduler(SchedulerError),
    /// Scheduler deployment values were invalid.
    SchedulerConfig(&'static str),
    /// G1-G5 denied the request before it reached the worker pool.
    GateBlocked(GateDecision),
    /// The Rust-owned state root rejected or failed to persist.
    StateStore(String),
    /// The requested lifecycle operation is not valid in the current phase.
    InvalidLifecycle(LifecycleState),
    /// The task handle is absent or has already been reaped.
    InvalidHandle,
    /// A task is still ready or running and cannot be reaped.
    TaskNotTerminal(RuntimeTaskState),
    /// A bounded reaper sweep must inspect at least one task.
    InvalidReapBudget,
    /// The runtime cannot accept new work after shutdown begins.
    ShuttingDown,
    /// A persistent root requires an explicit recovery acknowledgement before boot.
    RecoveryRequired(crate::recovery::RecoveryAction),
    /// The supplied recovery decision does not match the current root.
    RecoveryDecisionStale,
    /// Recovery acknowledgement was supplied for a root that does not need it.
    RecoveryNotRequired(crate::recovery::RecoveryAction),
}

/// Benchmark-only lock-wait evidence for runtime admission.
///
/// Both counters accumulate only after a `try_read` or `try_lock` reports
/// contention. The normal runtime submission path neither reads a clock nor
/// updates these counters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RuntimeLockWaitSnapshot {
    /// Time blocked by the lifecycle/shutdown admission barrier.
    /// Nanoseconds spent waiting for queue admission.
    pub admission_wait_ns: u64,
    /// Time blocked while registering a task in its shard-local task book.
    /// Nanoseconds spent waiting on task-book locks.
    pub task_book_wait_ns: u64,
}

impl RuntimeLockWaitSnapshot {
    /// Return the aggregate blocked time recorded by benchmark-only admission.
    pub const fn total_ns(self) -> u64 {
        self.admission_wait_ns
            .saturating_add(self.task_book_wait_ns)
    }
}

#[derive(Default)]
struct RuntimeLockWaitMetrics {
    admission_wait_ns: AtomicU64,
    task_book_wait_ns: AtomicU64,
}

struct RuntimeTaskBook {
    shards: Vec<StdMutex<BTreeMap<u64, RuntimeTaskState>>>,
    metrics: Arc<RuntimeLockWaitMetrics>,
}

impl RuntimeTaskBook {
    fn new(shard_count: u32, metrics: Arc<RuntimeLockWaitMetrics>) -> Self {
        let mut shards = Vec::with_capacity(shard_count as usize);
        for _ in 0..shard_count {
            shards.push(StdMutex::new(BTreeMap::new()));
        }
        Self { shards, metrics }
    }

    fn insert(&self, handle: ProcessHandle, state: RuntimeTaskState, observed: bool) {
        self.lock_shard(handle, observed)
            .insert(handle.raw(), state);
    }

    fn state(&self, handle: ProcessHandle) -> Option<RuntimeTaskState> {
        self.lock_shard(handle, false).get(&handle.raw()).copied()
    }

    fn set_state(&self, handle: ProcessHandle, state: RuntimeTaskState) {
        self.lock_shard(handle, false).insert(handle.raw(), state);
    }

    fn cancel_if_ready(&self, handle: ProcessHandle) -> bool {
        let mut tasks = self.lock_shard(handle, false);
        if tasks.get(&handle.raw()) == Some(&RuntimeTaskState::Ready) {
            tasks.insert(handle.raw(), RuntimeTaskState::Cancelled);
            true
        } else {
            false
        }
    }

    fn remove(&self, handle: ProcessHandle) {
        self.lock_shard(handle, false).remove(&handle.raw());
    }

    fn handles_up_to(&self, limit: usize) -> Vec<ProcessHandle> {
        if limit == 0 {
            return Vec::new();
        }
        let mut handles = Vec::with_capacity(limit);
        for shard in &self.shards {
            let tasks = shard.lock().unwrap_or_else(PoisonError::into_inner);
            for raw in tasks.keys() {
                if handles.len() == limit {
                    return handles;
                }
                if let Some(handle) = ProcessHandle::from_raw(*raw) {
                    handles.push(handle);
                }
            }
        }
        handles
    }

    fn snapshot_counts(&self) -> (usize, usize) {
        self.shards.iter().fold((0, 0), |(count, terminal), shard| {
            let tasks = shard.lock().unwrap_or_else(PoisonError::into_inner);
            (
                count.saturating_add(tasks.len()),
                terminal.saturating_add(tasks.values().filter(|state| state.is_terminal()).count()),
            )
        })
    }

    fn reset_observed_wait(&self) {
        self.metrics.admission_wait_ns.store(0, Ordering::Release);
        self.metrics.task_book_wait_ns.store(0, Ordering::Release);
    }

    fn observed_wait(&self) -> RuntimeLockWaitSnapshot {
        RuntimeLockWaitSnapshot {
            admission_wait_ns: self.metrics.admission_wait_ns.load(Ordering::Acquire),
            task_book_wait_ns: self.metrics.task_book_wait_ns.load(Ordering::Acquire),
        }
    }

    fn lock_shard(
        &self,
        handle: ProcessHandle,
        observed: bool,
    ) -> MutexGuard<'_, BTreeMap<u64, RuntimeTaskState>> {
        let shard = &self.shards[handle.slot() as usize % self.shards.len()];
        if !observed {
            return shard.lock().unwrap_or_else(PoisonError::into_inner);
        }
        match shard.try_lock() {
            Ok(tasks) => tasks,
            Err(TryLockError::Poisoned(error)) => error.into_inner(),
            Err(TryLockError::WouldBlock) => {
                let started = Instant::now();
                let tasks = shard.lock().unwrap_or_else(PoisonError::into_inner);
                self.metrics.task_book_wait_ns.fetch_add(
                    started.elapsed().as_nanos().try_into().unwrap_or(u64::MAX),
                    Ordering::Relaxed,
                );
                tasks
            }
        }
    }
}

/// A submitted runtime task and its generation-safe process identity.
#[derive(Clone)]
pub struct RuntimeTask {
    handle: ProcessHandle,
    result: TaskHandle,
    tasks: Arc<RuntimeTaskBook>,
    scheduler: Arc<KernelScheduler>,
}

impl RuntimeTask {
    /// Return the opaque process handle assigned to this task.
    pub const fn handle(&self) -> ProcessHandle {
        self.handle
    }

    /// Wait for the task result and synchronize terminal state accounting.
    ///
    /// # Errors
    ///
    /// TaskHandleError variants describe cancellation, deadline expiry,
    /// structured executor failure, or wait timeouts; panics are already
    /// folded into structured failures upstream.
    pub fn result(&self, timeout: Option<Duration>) -> Result<Value, TaskHandleError> {
        let result = self.result.result(timeout);
        if let Err(error) = &result {
            let state = match error {
                TaskHandleError::Cancelled(_) => Some(RuntimeTaskState::Cancelled),
                TaskHandleError::TaskTimeout => Some(RuntimeTaskState::TimedOut),
                TaskHandleError::Timeout => None,
                TaskHandleError::Failed(_) => Some(RuntimeTaskState::Failed),
            };
            if let Some(state) = state {
                // A task may fail before its wrapper enters the worker (eviction,
                // shutdown rejection, or queue admission failure). In that case
                // no completion callback can release the scheduler state.
                let _ = self.scheduler.stop_direct(self.handle);
                self.tasks.set_state(self.handle, state);
            }
        }
        result
    }

    /// Request cooperative cancellation before the worker starts execution.
    pub fn cancel(&self, reason: impl Into<String>) -> bool {
        let accepted = self.result.cancel(reason);
        if accepted
            && self.tasks.cancel_if_ready(self.handle)
            && self.scheduler.stop_direct(self.handle).is_err()
        {
            self.tasks.set_state(self.handle, RuntimeTaskState::Ready);
        }
        accepted
    }

    /// Return whether the worker has produced a terminal result.
    pub fn done(&self) -> bool {
        self.result.done()
    }

    /// Return the latest runtime-owned task state.
    pub fn state(&self) -> Option<RuntimeTaskState> {
        self.tasks.state(self.handle)
    }
}

/// Rust-owned execution host candidate; not the production boot authority.
pub struct KernelRuntime {
    assembly: KernelAssembly,
    lifecycle: Arc<LifecycleRegistry>,
    state_store: Option<StdMutex<StateStore>>,
    execution_store: Option<StdMutex<ExecutionStore>>,
    sessions: SessionBook,
    terminals: TerminalBook,
    agent_loops: AgentLoopBook,
    scheduler: Arc<KernelScheduler>,
    admission: RwLock<()>,
    gatechain: Arc<GateChain>,
    capability: Arc<CapabilityAuthority>,
    workers: WorkerPool,
    tasks: Arc<RuntimeTaskBook>,
    recovery_action: StdMutex<Option<RecoveryAction>>,
}

impl KernelRuntime {
    /// Assemble a halted runtime without performing provider side effects.
    ///
    /// # Errors
    ///
    /// RuntimeError when assembly/config validation fails.
    pub fn new(spec: AssemblySpec, config: RuntimeConfig) -> Result<Self, RuntimeError> {
        let assembly = KernelAssembly::assemble(spec).map_err(RuntimeError::Assembly)?;
        let scheduler = KernelScheduler::new(SchedulerConfig::new(
            config.max_processes,
            config.shard_count,
            config.workers.queue_size,
        ))
        .map_err(RuntimeError::SchedulerConfig)?;
        let workers = WorkerPool::new(config.workers).map_err(RuntimeError::WorkerConfig)?;
        let sessions = SessionBook::new(config.shard_count as usize).map_err(|error| {
            RuntimeError::Session(format!("session book initialization failed: {error:?}"))
        })?;
        Ok(Self {
            assembly,
            lifecycle: Arc::new(LifecycleRegistry::new()),
            state_store: None,
            execution_store: None,
            sessions,
            terminals: TerminalBook::new(),
            agent_loops: AgentLoopBook::new(),
            scheduler: Arc::new(scheduler),
            admission: RwLock::new(()),
            gatechain: Arc::new(GateChain::new()),
            capability: Arc::new(CapabilityAuthority::new()),
            workers,
            tasks: runtime_task_book(config.shard_count),
            recovery_action: StdMutex::new(None),
        })
    }

    /// Open a fresh Rust-owned state root and attach durable lifecycle writes.
    ///
    /// # Errors
    ///
    /// RuntimeError::StateStore when the persistent root cannot be opened
    /// or its checkpoint diverges from the requested layout.
    pub fn open_persistent(
        spec: AssemblySpec,
        config: RuntimeConfig,
        root: impl AsRef<std::path::Path>,
    ) -> Result<Self, RuntimeError> {
        let root = root.as_ref();
        let expected_root = spec.state_root.clone();
        if expected_root != root.to_string_lossy() {
            return Err(RuntimeError::StateStore(format!(
                "assembly state root '{}' does not match runtime root '{}'",
                expected_root,
                root.display()
            )));
        }
        let assembly = KernelAssembly::assemble(spec).map_err(RuntimeError::Assembly)?;
        let mut state_store = StateStore::open(root, assembly.snapshot().contract_version)
            .map_err(map_state_store_error)?;
        if state_store.action() == crate::state_layout::StateAction::Recover {
            state_store.recover().map_err(map_state_store_error)?;
        }
        let lifecycle = state_store.lifecycle_handle();
        let execution_store = ExecutionStore::open(root).map_err(map_execution_store_error)?;
        let execution_document = execution_store
            .document()
            .map_err(map_execution_store_error)?;
        let execution_state = execution_store
            .load_state(config.shard_count as usize)
            .map_err(map_execution_store_error)?;
        let recovery_action =
            match RecoveryTrigger::decide(lifecycle.state(), Some(&execution_document)).action {
                RecoveryAction::Fresh | RecoveryAction::ResumeClean => None,
                action => Some(action),
            };
        let scheduler = KernelScheduler::new(SchedulerConfig::new(
            config.max_processes,
            config.shard_count,
            config.workers.queue_size,
        ))
        .map_err(RuntimeError::SchedulerConfig)?;
        let workers = WorkerPool::new(config.workers).map_err(RuntimeError::WorkerConfig)?;
        Ok(Self {
            assembly,
            lifecycle,
            state_store: Some(StdMutex::new(state_store)),
            execution_store: Some(StdMutex::new(execution_store)),
            sessions: execution_state.sessions,
            terminals: execution_state.terminals,
            agent_loops: execution_state.loops,
            scheduler: Arc::new(scheduler),
            admission: RwLock::new(()),
            gatechain: Arc::new(GateChain::new()),
            capability: Arc::new(CapabilityAuthority::new()),
            workers,
            tasks: runtime_task_book(config.shard_count),
            recovery_action: StdMutex::new(recovery_action),
        })
    }

    /// Return the validated assembly metadata held by this runtime.
    pub const fn assembly(&self) -> &KernelAssembly {
        &self.assembly
    }

    /// Return the Rust-owned G1-G5 chain used by gated submission.
    pub fn gatechain(&self) -> Arc<GateChain> {
        Arc::clone(&self.gatechain)
    }

    /// Return the single capability authority used by gated submission.
    pub fn capability_authority(&self) -> Arc<CapabilityAuthority> {
        Arc::clone(&self.capability)
    }

    /// Return the Rust-owned session truth book used by this runtime.
    pub const fn sessions(&self) -> &SessionBook {
        &self.sessions
    }

    /// Return the Rust-owned terminal metadata and mailbox book.
    pub const fn terminals(&self) -> &TerminalBook {
        &self.terminals
    }

    /// Return the Rust-owned logical AgentLoop identity book.
    pub const fn agent_loops(&self) -> &AgentLoopBook {
        &self.agent_loops
    }

    /// Persist the three execution books through the Rust-owned checkpoint.
    ///
    /// This API is explicit for callers that need an unclean checkpoint before
    /// a host restart. A clean checkpoint is also written automatically during
    /// a successful persistent shutdown, before its lifecycle becomes halted.
    pub fn checkpoint_execution(
        &self,
        clean_shutdown: bool,
    ) -> Result<ExecutionStoreDocument, RuntimeError> {
        let store = self
            .execution_store
            .as_ref()
            .ok_or_else(|| RuntimeError::ExecutionStore("runtime is not persistent".to_owned()))?;
        let mut store = store.lock().unwrap_or_else(PoisonError::into_inner);
        let document = store
            .save(
                &self.sessions,
                &self.terminals,
                &self.agent_loops,
                clean_shutdown,
            )
            .map_err(map_execution_store_error)?;
        let action = RecoveryTrigger::decide(self.lifecycle.state(), Some(&document)).action;
        let mut recovery_action = self
            .recovery_action
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        *recovery_action = match action {
            RecoveryAction::Fresh | RecoveryAction::ResumeClean => None,
            action => Some(action),
        };
        Ok(document)
    }

    /// Return a side-effect-free recovery decision for this persistent root.
    ///
    /// The trigger is intentionally separate from `boot`: callers must review
    /// `RecoverUnclean` and perform session/terminal/loop rebind steps before
    /// requesting any execution. Non-persistent runtimes cannot claim a
    /// checkpoint decision.
    pub fn recovery_decision(&self) -> Result<RecoveryDecision, RuntimeError> {
        let store = self
            .execution_store
            .as_ref()
            .ok_or_else(|| RuntimeError::ExecutionStore("runtime is not persistent".to_owned()))?;
        let store = store.lock().unwrap_or_else(PoisonError::into_inner);
        let document = store.document().map_err(map_execution_store_error)?;
        Ok(RecoveryTrigger::decide(
            self.lifecycle.state(),
            Some(&document),
        ))
    }

    /// Acknowledge an unclean recovery decision after caller-owned rebind work.
    ///
    /// This only clears the in-memory boot gate for this runtime instance. It
    /// does not mutate the books, checkpoint, lifecycle, process handles, or
    /// terminal bindings; those remain explicit adapter responsibilities.
    pub fn acknowledge_recovery(&self, decision: &RecoveryDecision) -> Result<(), RuntimeError> {
        let _admission = self
            .admission
            .write()
            .unwrap_or_else(PoisonError::into_inner);
        let current = self.recovery_decision()?;
        if current != *decision {
            return Err(RuntimeError::RecoveryDecisionStale);
        }
        if current.action != RecoveryAction::RecoverUnclean {
            return Err(RuntimeError::RecoveryNotRequired(current.action));
        }
        let mut recovery_action = self
            .recovery_action
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if *recovery_action != Some(RecoveryAction::RecoverUnclean) {
            return Err(RuntimeError::RecoveryDecisionStale);
        }
        *recovery_action = None;
        Ok(())
    }

    /// Submit a capability only after the Rust G1-G5 chain permits it.
    ///
    /// # Errors
    ///
    /// RuntimeError::GateBlocked carrying the failing GateDecision; the
    /// denial is audited before the error is returned.
    pub fn submit_gated(
        &self,
        gate: GateRequest,
        request: CapabilityRequest,
    ) -> Result<RuntimeTask, RuntimeError> {
        if gate.tool != request.name || gate.agent_id != request.agent_id {
            self.capability.audit().record_fields(
                "capability.gate_mismatch",
                request.agent_id.clone(),
                false,
                "gate/request identity mismatch",
                "gate and capability identities must match",
            );
            return Err(RuntimeError::GateBlocked(GateDecision::Block));
        }
        let check = self.gatechain.check(&gate);
        if !check.allowed {
            self.capability.audit().record_fields(
                "capability.gate",
                gate.agent_id.clone(),
                false,
                format!("gatechain decision {}", check.decision.as_str()),
                gate.tool.clone(),
            );
            return Err(RuntimeError::GateBlocked(check.decision));
        }
        let authority = Arc::clone(&self.capability);
        self.submit(Box::new(move || {
            let result = authority.invoke(request);
            capability_value(result)
        }))
    }

    /// Boot the runtime through booting to active without running callbacks.
    ///
    /// # Errors
    ///
    /// RuntimeError when the halted→booting→active transition or any boot
    /// callback fails; state stays consistent for a retry.
    pub fn boot(&self) -> Result<RuntimeSnapshot, RuntimeError> {
        let _admission = self
            .admission
            .write()
            .unwrap_or_else(PoisonError::into_inner);
        if let Some(action) = *self
            .recovery_action
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
        {
            return Err(RuntimeError::RecoveryRequired(action));
        }
        let bootable = self.lifecycle.state() == LifecycleState::Halted
            || (self.state_store.is_some() && self.lifecycle.state() == LifecycleState::Crashed);
        if !bootable {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        if !self.assembly.is_locked() {
            return Err(RuntimeError::ShuttingDown);
        }
        if let Some(state_store) = &self.state_store {
            let mut state_store = state_store.lock().unwrap_or_else(PoisonError::into_inner);
            state_store.begin_boot().map_err(map_state_store_error)?;
            state_store.mark_active().map_err(map_state_store_error)?;
        } else {
            if !self.lifecycle.transition(LifecycleState::Booting)
                || !self.lifecycle.transition(LifecycleState::Active)
            {
                return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
            }
            self.lifecycle.record_boot_success_at("runtime");
        }
        Ok(self.snapshot())
    }

    /// Submit a closure to the bounded worker pool and assign a process handle.
    ///
    /// # Errors
    ///
    /// RuntimeError::GateBlocked before enqueueing; Capacity/State errors mirror the pool.
    pub fn submit(&self, action: TaskFn) -> Result<RuntimeTask, RuntimeError> {
        self.submit_inner(action, None, false)
    }

    /// Submit a closure with an execution deadline enforced by the worker.
    pub fn submit_with_timeout(
        &self,
        action: TaskFn,
        timeout: Duration,
    ) -> Result<RuntimeTask, RuntimeError> {
        self.submit_inner(action, Some(timeout), false)
    }

    /// Submit an ordered task batch through one WorkerPool admission boundary.
    ///
    /// Each returned task retains the same cancellation, result, deadline-free,
    /// and reap behavior as [`Self::submit`]. If process reservation fails,
    /// the complete batch is rolled back before any closure reaches a worker.
    ///
    /// # Errors
    ///
    /// Per-item gate/pool errors as above, positionally preserved.
    pub fn submit_batch(&self, actions: Vec<TaskFn>) -> Result<Vec<RuntimeTask>, RuntimeError> {
        self.submit_batch_inner(actions, false, false)
    }

    /// Submit a batch only when the worker queue can retain every item.
    ///
    /// Unlike [`Self::submit_batch`], this path never evicts older queued
    /// work. A queue-capacity or shutdown rejection rolls back every reserved
    /// scheduler/task handle before returning.
    pub fn submit_batch_strict(
        &self,
        actions: Vec<TaskFn>,
    ) -> Result<Vec<RuntimeTask>, RuntimeError> {
        self.submit_batch_inner(actions, false, true)
    }

    /// Submit one benchmark task while recording only contended admission waits.
    ///
    /// This API is for fixed-work evidence runners. Production callers should
    /// use [`Self::submit`] or [`Self::submit_with_timeout`], which avoid
    /// clock reads and counter updates on the uncontended path.
    ///
    /// # Errors
    ///
    /// RuntimeError variants mirroring `submit` plus observer wiring failures.
    pub fn submit_observed(&self, action: TaskFn) -> Result<RuntimeTask, RuntimeError> {
        self.submit_inner(action, None, true)
    }

    /// Submit one benchmark batch while recording only contended admission waits.
    ///
    /// This is the batch counterpart to [`Self::submit_observed`]. It exists
    /// only for fixed-work evidence and does not alter normal submission
    /// instrumentation or runtime authority.
    pub fn submit_batch_observed(
        &self,
        actions: Vec<TaskFn>,
    ) -> Result<Vec<RuntimeTask>, RuntimeError> {
        self.submit_batch_inner(actions, true, false)
    }

    /// Reset benchmark-only runtime admission lock-wait counters.
    pub fn reset_observed_lock_wait(&self) {
        self.tasks.reset_observed_wait();
    }

    /// Return benchmark-only runtime admission lock-wait counters.
    pub fn observed_lock_wait(&self) -> RuntimeLockWaitSnapshot {
        self.tasks.observed_wait()
    }

    fn submit_inner(
        &self,
        action: TaskFn,
        timeout: Option<Duration>,
        observed: bool,
    ) -> Result<RuntimeTask, RuntimeError> {
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        let _admission = self.read_admission(observed);
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        let handle = self.reserve_task(observed)?;
        let action = self.bind_action(handle, action);
        let result = match timeout {
            Some(timeout) => self.workers.submit_result_with_timeout(action, timeout),
            None => self.workers.submit_result(action),
        };
        Ok(self.runtime_task(handle, result))
    }

    fn submit_batch_inner(
        &self,
        actions: Vec<TaskFn>,
        observed: bool,
        strict: bool,
    ) -> Result<Vec<RuntimeTask>, RuntimeError> {
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        let _admission = self.read_admission(observed);
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        if actions.is_empty() {
            return Ok(Vec::new());
        }
        let handles = self.reserve_task_batch(actions.len(), observed)?;
        let actions = handles
            .iter()
            .copied()
            .zip(actions)
            .map(|(handle, action)| self.bind_action(handle, action))
            .collect::<Vec<_>>();
        let results = if strict {
            match self.workers.submit_result_batch_strict(actions) {
                Ok(results) => results,
                Err(error) => {
                    self.rollback_reserved_tasks(&handles);
                    return Err(RuntimeError::WorkerRejected(error));
                }
            }
        } else {
            self.workers.submit_result_batch(actions)
        };
        Ok(handles
            .into_iter()
            .zip(results)
            .map(|(handle, result)| self.runtime_task(handle, result))
            .collect())
    }

    fn bind_action(&self, handle: ProcessHandle, action: TaskFn) -> TaskFn {
        let tasks = Arc::clone(&self.tasks);
        let scheduler = Arc::clone(&self.scheduler);
        Box::new(move || {
            tasks.set_state(handle, RuntimeTaskState::Running);
            let result = catch_unwind(AssertUnwindSafe(action))
                .unwrap_or_else(|_| Err("task panicked".to_owned()));
            let _ = scheduler.complete_direct(handle);
            tasks.set_state(
                handle,
                if result.is_ok() {
                    RuntimeTaskState::Succeeded
                } else {
                    RuntimeTaskState::Failed
                },
            );
            result
        })
    }

    fn runtime_task(&self, handle: ProcessHandle, result: TaskHandle) -> RuntimeTask {
        RuntimeTask {
            handle,
            result,
            tasks: Arc::clone(&self.tasks),
            scheduler: Arc::clone(&self.scheduler),
        }
    }

    /// Reap a terminal task and release its generation-safe process slot.
    ///
    /// # Errors
    ///
    /// RuntimeError when the handle is not yet reaped-able.
    pub fn reap(&self, handle: ProcessHandle) -> Result<(), RuntimeError> {
        let state = self
            .tasks
            .state(handle)
            .ok_or(RuntimeError::InvalidHandle)?;
        if !state.is_terminal() {
            return Err(RuntimeError::TaskNotTerminal(state));
        }
        self.scheduler
            .reap(handle)
            .map_err(RuntimeError::Scheduler)?;
        self.tasks.remove(handle);
        Ok(())
    }

    /// Reap up to `max_tasks` terminal tasks without blocking on live work.
    ///
    /// This is a caller-owned mechanism seam for future shutdown/reaper
    /// integration. It never starts a background thread and never changes the
    /// lifecycle phase; live tasks remain owned and are reported as pending.
    ///
    /// # Errors
    ///
    /// RuntimeError when the sweep cannot observe children; per-child outcomes are counters, not errors.
    pub fn reap_finished(&self, max_tasks: usize) -> Result<RuntimeReapReport, RuntimeError> {
        if max_tasks == 0 {
            return Err(RuntimeError::InvalidReapBudget);
        }
        let handles = self.tasks.handles_up_to(max_tasks);
        let mut report = RuntimeReapReport {
            inspected: handles.len() as u64,
            ..RuntimeReapReport::default()
        };
        for handle in handles {
            let Some(state) = self.tasks.state(handle) else {
                report.unavailable = report.unavailable.saturating_add(1);
                continue;
            };
            if !state.is_terminal() {
                report.pending = report.pending.saturating_add(1);
                continue;
            }
            match self.scheduler.reap(handle) {
                Ok(()) => {
                    self.tasks.remove(handle);
                    report.reaped = report.reaped.saturating_add(1);
                }
                Err(SchedulerError::InvalidHandle) => {
                    report.unavailable = report.unavailable.saturating_add(1);
                }
                Err(_) => {
                    report.errors = report.errors.saturating_add(1);
                }
            }
        }
        Ok(report)
    }

    fn reserve_task(&self, observed: bool) -> Result<ProcessHandle, RuntimeError> {
        let handle = self.scheduler.spawn().map_err(RuntimeError::Scheduler)?;
        self.tasks.insert(handle, RuntimeTaskState::Ready, observed);
        if let Err(error) = self.scheduler.dispatch_direct(handle) {
            self.tasks.remove(handle);
            let _ = self.scheduler.reap(handle);
            return Err(RuntimeError::Scheduler(error));
        }
        Ok(handle)
    }

    fn reserve_task_batch(
        &self,
        count: usize,
        observed: bool,
    ) -> Result<Vec<ProcessHandle>, RuntimeError> {
        let mut handles = Vec::with_capacity(count);
        for _ in 0..count {
            match self.reserve_task(observed) {
                Ok(handle) => handles.push(handle),
                Err(error) => {
                    self.rollback_reserved_tasks(&handles);
                    return Err(error);
                }
            }
        }
        Ok(handles)
    }

    fn rollback_reserved_tasks(&self, handles: &[ProcessHandle]) {
        for handle in handles {
            let _ = self.scheduler.stop_direct(*handle);
            let _ = self.scheduler.reap(*handle);
            self.tasks.remove(*handle);
        }
    }

    fn read_admission(&self, observed: bool) -> RwLockReadGuard<'_, ()> {
        if !observed {
            return self
                .admission
                .read()
                .unwrap_or_else(PoisonError::into_inner);
        }
        match self.admission.try_read() {
            Ok(admission) => admission,
            Err(TryLockError::Poisoned(error)) => error.into_inner(),
            Err(TryLockError::WouldBlock) => {
                let started = Instant::now();
                let admission = self
                    .admission
                    .read()
                    .unwrap_or_else(PoisonError::into_inner);
                self.tasks.metrics.admission_wait_ns.fetch_add(
                    started.elapsed().as_nanos().try_into().unwrap_or(u64::MAX),
                    Ordering::Relaxed,
                );
                admission
            }
        }
    }

    /// Return scheduler queue metrics; direct runtime dispatch should remain zero.
    pub fn scheduler_queue_metrics(&self) -> crate::substrate::QueueMetricSnapshot {
        self.scheduler.queue_metrics()
    }

    /// Drain workers and transition the runtime to halted.
    ///
    /// # Errors
    ///
    /// RuntimeError when drain cannot complete within the timeout; tasks keep their terminal states.
    pub fn shutdown(&self, timeout: Option<Duration>) -> Result<RuntimeSnapshot, RuntimeError> {
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        if !self.lifecycle.transition(LifecycleState::Draining) {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        // Publish draining before waiting for the exclusive barrier so fresh
        // readers fail closed while already-admitted submissions drain.
        let _admission = self
            .admission
            .write()
            .unwrap_or_else(PoisonError::into_inner);
        let result = self.workers.shutdown(true, timeout);
        if result.get("success") != Some(&json!(true)) {
            if let Some(state_store) = &self.state_store {
                let mut state_store = state_store.lock().unwrap_or_else(PoisonError::into_inner);
                let _ = state_store.shutdown(false);
            } else {
                let _ = self.lifecycle.transition(LifecycleState::Crashed);
            }
            return Err(RuntimeError::ShuttingDown);
        }
        if self.execution_store.is_some()
            && let Err(error) = self.checkpoint_execution(true)
        {
            // Preserve the current books as an unclean checkpoint before
            // publishing the lifecycle failure, so recovery cannot reopen
            // a stale clean document after a rejected clean shutdown.
            let _ = self.checkpoint_execution(false);
            if let Some(state_store) = &self.state_store {
                let mut state_store = state_store.lock().unwrap_or_else(PoisonError::into_inner);
                let _ = state_store.shutdown(false);
            }
            return Err(error);
        }
        if let Some(state_store) = &self.state_store {
            let mut state_store = state_store.lock().unwrap_or_else(PoisonError::into_inner);
            state_store.shutdown(true).map_err(map_state_store_error)?;
        } else {
            if !self.lifecycle.transition(LifecycleState::Halted) {
                return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
            }
            self.lifecycle.record_shutdown_at(true, "runtime");
        }
        *self
            .recovery_action
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = None;
        Ok(self.snapshot())
    }

    /// Return lifecycle, task, and worker metrics without mutating state.
    pub fn snapshot(&self) -> RuntimeSnapshot {
        let (task_count, terminal_tasks) = self.tasks.snapshot_counts();
        RuntimeSnapshot {
            lifecycle: self.lifecycle.state(),
            task_count,
            terminal_tasks,
            worker_stats: self.workers.stats(),
        }
    }
}

impl Drop for KernelRuntime {
    fn drop(&mut self) {
        let lifecycle = self.lifecycle.state();
        let _ = self.workers.shutdown(true, Some(Duration::from_secs(1)));
        if let Some(state_store) = &self.state_store
            && !matches!(lifecycle, LifecycleState::Halted)
        {
            let mut state_store = state_store.lock().unwrap_or_else(PoisonError::into_inner);
            let _ = state_store.shutdown(false);
        }
    }
}

fn runtime_task_book(shard_count: u32) -> Arc<RuntimeTaskBook> {
    let metrics = Arc::new(RuntimeLockWaitMetrics::default());
    Arc::new(RuntimeTaskBook::new(shard_count, metrics))
}

fn map_state_store_error(error: StateStoreError) -> RuntimeError {
    RuntimeError::StateStore(error.to_string())
}

fn map_execution_store_error(error: ExecutionStoreError) -> RuntimeError {
    RuntimeError::ExecutionStore(error.to_string())
}

fn capability_value(result: CapabilityResult) -> Result<Value, String> {
    if !result.success {
        return Err(result.error);
    }
    serde_json::to_value(result)
        .map_err(|error| format!("capability result serialization failed: {error}"))
}
