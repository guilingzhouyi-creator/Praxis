//! Rust-owned execution host candidate for the clean-break kernel.
//!
//! This module composes the validated assembly metadata, lifecycle FSM,
//! generation-safe process handles, and bounded worker pool into one explicit
//! execution boundary. It accepts already-bound Rust closures only; Python,
//! PTY, AgentLoop, prompt, tool, provider, and frontend policy remain outside
//! this candidate until cutover and recovery gates are complete.

use std::collections::BTreeMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Mutex as StdMutex, MutexGuard, PoisonError};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::assembly::{AssemblyError, AssemblySpec, KernelAssembly};
use crate::capability::CapabilityAuthority;
use crate::contract::{CapabilityRequest, CapabilityResult};
use crate::gatechain::{GateChain, GateDecision, GateRequest};
use crate::lifecycle::{LifecycleRegistry, LifecycleState};
use crate::scheduler::{KernelScheduler, SchedulerConfig, SchedulerError};
use crate::state_store::{StateStore, StateStoreError};
use crate::substrate::ProcessHandle;
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
    pub max_processes: u32,
    /// Number of independent scheduler state shards.
    pub shard_count: u32,
    /// Worker-pool sizing and bounded queue limits.
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
    pub lifecycle: LifecycleState,
    /// Number of allocated, unreaped task handles.
    pub task_count: usize,
    /// Number of terminal tasks still awaiting reap.
    pub terminal_tasks: usize,
    /// Worker-pool metrics at the same observation point.
    pub worker_stats: BTreeMap<String, Value>,
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
    /// The runtime cannot accept new work after shutdown begins.
    ShuttingDown,
}

/// A submitted runtime task and its generation-safe process identity.
#[derive(Clone)]
pub struct RuntimeTask {
    handle: ProcessHandle,
    result: TaskHandle,
    tasks: Arc<StdMutex<BTreeMap<u64, RuntimeTaskState>>>,
    scheduler: Arc<KernelScheduler>,
}

impl RuntimeTask {
    /// Return the opaque process handle assigned to this task.
    pub const fn handle(&self) -> ProcessHandle {
        self.handle
    }

    /// Wait for the task result and synchronize terminal state accounting.
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
                set_task_state(&self.tasks, self.handle, state);
            }
        }
        result
    }

    /// Request cooperative cancellation before the worker starts execution.
    pub fn cancel(&self, reason: impl Into<String>) -> bool {
        let accepted = self.result.cancel(reason);
        if accepted {
            let mut tasks = lock_tasks(&self.tasks);
            if tasks.get(&self.handle.raw()) == Some(&RuntimeTaskState::Ready)
                && self.scheduler.stop_direct(self.handle).is_ok()
            {
                tasks.insert(self.handle.raw(), RuntimeTaskState::Cancelled);
            }
        }
        accepted
    }

    /// Return whether the worker has produced a terminal result.
    pub fn done(&self) -> bool {
        self.result.done()
    }

    /// Return the latest runtime-owned task state.
    pub fn state(&self) -> Option<RuntimeTaskState> {
        lock_tasks(&self.tasks).get(&self.handle.raw()).copied()
    }
}

/// Rust-owned execution host candidate; not the production boot authority.
pub struct KernelRuntime {
    assembly: KernelAssembly,
    lifecycle: Arc<LifecycleRegistry>,
    state_store: Option<StdMutex<StateStore>>,
    scheduler: Arc<KernelScheduler>,
    admission: StdMutex<()>,
    gatechain: Arc<GateChain>,
    capability: Arc<CapabilityAuthority>,
    workers: WorkerPool,
    tasks: Arc<StdMutex<BTreeMap<u64, RuntimeTaskState>>>,
}

impl KernelRuntime {
    /// Assemble a halted runtime without performing provider side effects.
    pub fn new(spec: AssemblySpec, config: RuntimeConfig) -> Result<Self, RuntimeError> {
        let assembly = KernelAssembly::assemble(spec).map_err(RuntimeError::Assembly)?;
        let scheduler = KernelScheduler::new(SchedulerConfig::new(
            config.max_processes,
            config.shard_count,
            config.workers.queue_size,
        ))
        .map_err(RuntimeError::SchedulerConfig)?;
        let workers = WorkerPool::new(config.workers).map_err(RuntimeError::WorkerConfig)?;
        Ok(Self {
            assembly,
            lifecycle: Arc::new(LifecycleRegistry::new()),
            state_store: None,
            scheduler: Arc::new(scheduler),
            admission: StdMutex::new(()),
            gatechain: Arc::new(GateChain::new()),
            capability: Arc::new(CapabilityAuthority::new()),
            workers,
            tasks: Arc::new(StdMutex::new(BTreeMap::new())),
        })
    }

    /// Open a fresh Rust-owned state root and attach durable lifecycle writes.
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
            scheduler: Arc::new(scheduler),
            admission: StdMutex::new(()),
            gatechain: Arc::new(GateChain::new()),
            capability: Arc::new(CapabilityAuthority::new()),
            workers,
            tasks: Arc::new(StdMutex::new(BTreeMap::new())),
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

    /// Submit a capability only after the Rust G1-G5 chain permits it.
    pub fn submit_gated(
        &self,
        gate: GateRequest,
        request: CapabilityRequest,
    ) -> Result<RuntimeTask, RuntimeError> {
        if gate.tool != request.name || gate.agent_id != request.agent_id {
            return Err(RuntimeError::GateBlocked(GateDecision::Block));
        }
        let check = self.gatechain.check(&gate);
        if !check.allowed {
            return Err(RuntimeError::GateBlocked(check.decision));
        }
        let authority = Arc::clone(&self.capability);
        self.submit(Box::new(move || {
            let result = authority.invoke(request);
            capability_value(result)
        }))
    }

    /// Boot the runtime through booting to active without running callbacks.
    pub fn boot(&self) -> Result<RuntimeSnapshot, RuntimeError> {
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
    pub fn submit(&self, action: TaskFn) -> Result<RuntimeTask, RuntimeError> {
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        let handle = self.start_task()?;
        lock_tasks(&self.tasks).insert(handle.raw(), RuntimeTaskState::Ready);
        let tasks = Arc::clone(&self.tasks);
        let scheduler = Arc::clone(&self.scheduler);
        let action = Box::new(move || {
            set_task_state(&tasks, handle, RuntimeTaskState::Running);
            let result = catch_unwind(AssertUnwindSafe(action))
                .unwrap_or_else(|_| Err("task panicked".to_owned()));
            let _ = scheduler.complete_direct(handle);
            set_task_state(
                &tasks,
                handle,
                if result.is_ok() {
                    RuntimeTaskState::Succeeded
                } else {
                    RuntimeTaskState::Failed
                },
            );
            result
        });
        let result = self.workers.submit_result(action);
        Ok(RuntimeTask {
            handle,
            result,
            tasks: Arc::clone(&self.tasks),
            scheduler: Arc::clone(&self.scheduler),
        })
    }

    /// Submit a closure with an execution deadline enforced by the worker.
    pub fn submit_with_timeout(
        &self,
        action: TaskFn,
        timeout: Duration,
    ) -> Result<RuntimeTask, RuntimeError> {
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        let handle = self.start_task()?;
        lock_tasks(&self.tasks).insert(handle.raw(), RuntimeTaskState::Ready);
        let tasks = Arc::clone(&self.tasks);
        let scheduler = Arc::clone(&self.scheduler);
        let action = Box::new(move || {
            set_task_state(&tasks, handle, RuntimeTaskState::Running);
            let result = catch_unwind(AssertUnwindSafe(action))
                .unwrap_or_else(|_| Err("task panicked".to_owned()));
            let _ = scheduler.complete_direct(handle);
            set_task_state(
                &tasks,
                handle,
                if result.is_ok() {
                    RuntimeTaskState::Succeeded
                } else {
                    RuntimeTaskState::Failed
                },
            );
            result
        });
        let result = self.workers.submit_result_with_timeout(action, timeout);
        Ok(RuntimeTask {
            handle,
            result,
            tasks: Arc::clone(&self.tasks),
            scheduler: Arc::clone(&self.scheduler),
        })
    }

    /// Reap a terminal task and release its generation-safe process slot.
    pub fn reap(&self, handle: ProcessHandle) -> Result<(), RuntimeError> {
        let state = lock_tasks(&self.tasks)
            .get(&handle.raw())
            .copied()
            .ok_or(RuntimeError::InvalidHandle)?;
        if !state.is_terminal() {
            return Err(RuntimeError::TaskNotTerminal(state));
        }
        self.scheduler
            .reap(handle)
            .map_err(RuntimeError::Scheduler)?;
        lock_tasks(&self.tasks).remove(&handle.raw());
        Ok(())
    }

    fn start_task(&self) -> Result<ProcessHandle, RuntimeError> {
        let _admission = self
            .admission
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let handle = self.scheduler.spawn().map_err(RuntimeError::Scheduler)?;
        if let Err(error) = self.scheduler.dispatch_direct(handle) {
            let _ = self.scheduler.reap(handle);
            return Err(RuntimeError::Scheduler(error));
        }
        Ok(handle)
    }

    /// Return scheduler queue metrics; direct runtime dispatch should remain zero.
    pub fn scheduler_queue_metrics(&self) -> crate::substrate::QueueMetricSnapshot {
        self.scheduler.queue_metrics()
    }

    /// Drain workers and transition the runtime to halted.
    pub fn shutdown(&self, timeout: Option<Duration>) -> Result<RuntimeSnapshot, RuntimeError> {
        if self.lifecycle.state() != LifecycleState::Active {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
        if !self.lifecycle.transition(LifecycleState::Draining) {
            return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
        }
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
        if let Some(state_store) = &self.state_store {
            let mut state_store = state_store.lock().unwrap_or_else(PoisonError::into_inner);
            state_store.shutdown(true).map_err(map_state_store_error)?;
        } else {
            if !self.lifecycle.transition(LifecycleState::Halted) {
                return Err(RuntimeError::InvalidLifecycle(self.lifecycle.state()));
            }
            self.lifecycle.record_shutdown_at(true, "runtime");
        }
        Ok(self.snapshot())
    }

    /// Return lifecycle, task, and worker metrics without mutating state.
    pub fn snapshot(&self) -> RuntimeSnapshot {
        let tasks = lock_tasks(&self.tasks);
        RuntimeSnapshot {
            lifecycle: self.lifecycle.state(),
            task_count: tasks.len(),
            terminal_tasks: tasks.values().filter(|state| state.is_terminal()).count(),
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

fn lock_tasks(
    tasks: &Arc<StdMutex<BTreeMap<u64, RuntimeTaskState>>>,
) -> MutexGuard<'_, BTreeMap<u64, RuntimeTaskState>> {
    tasks.lock().unwrap_or_else(PoisonError::into_inner)
}

fn set_task_state(
    tasks: &Arc<StdMutex<BTreeMap<u64, RuntimeTaskState>>>,
    handle: ProcessHandle,
    state: RuntimeTaskState,
) {
    lock_tasks(tasks).insert(handle.raw(), state);
}

fn map_state_store_error(error: StateStoreError) -> RuntimeError {
    RuntimeError::StateStore(error.to_string())
}

fn capability_value(result: CapabilityResult) -> Result<Value, String> {
    if !result.success {
        return Err(result.error);
    }
    serde_json::to_value(result)
        .map_err(|error| format!("capability result serialization failed: {error}"))
}
