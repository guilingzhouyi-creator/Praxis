//! ProcessTable ownership bridge for managed child execution.
//!
//! `ManagedProcessBook` owns the host child and its bounded pipes, while
//! `ProcessTable` owns the kernel-visible identity and lifecycle.  This module
//! keeps the two concerns explicit: callers receive only the ProcessTable
//! handle, and the managed handle never crosses this adapter boundary.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, PoisonError, RwLock};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::contract::{ProcessOptions, ProcessResult};
use crate::managed_process::{
    ManagedProcessBook, ManagedProcessError, ManagedProcessState, ManagedWaitResult,
};
use crate::process::{ProcessState, ProcessTable};
use crate::process_adapter::ProcessAdapterConfig;
use crate::substrate::ProcessHandle;

/// Version of the ProcessTable-to-managed-child bridge contract.
pub const PROCESS_BRIDGE_CONTRACT_VERSION: u32 = 1;
/// Deadline used to clean up a child when table registration fails.
pub const PROCESS_BRIDGE_ROLLBACK_TIMEOUT: Duration = Duration::from_secs(1);

static NEXT_PROCESS_BRIDGE_ID: AtomicU64 = AtomicU64::new(1);

/// Public correlation snapshot with no host child or pipe objects.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessBridgeSnapshot {
    /// Version of the bridge value contract.
    pub contract_version: u32,
    /// ProcessTable-owned handle exposed to callers.
    pub handle: u64,
    /// Monotonic ProcessTable PID associated with the handle.
    pub pid: u64,
    /// ProcessTable lifecycle state.
    pub table_state: ProcessState,
    /// Managed child lifecycle state.
    pub managed_state: ManagedProcessState,
    /// Child return code after terminal observation.
    pub returncode: Option<i32>,
}

/// Result of one bounded, caller-driven finished-child sweep.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessReapReport {
    /// Number of bindings observed at the start of the sweep.
    pub inspected: u64,
    /// Number of children jointly reaped without an ownership error.
    pub reaped: u64,
    /// Number of live children left owned after the sweep.
    pub pending: u64,
    /// Number of bindings concurrently removed before observation.
    pub unavailable: u64,
    /// Number of terminal observations that hit a table or managed error.
    pub errors: u64,
}

/// Fail-closed errors at the ProcessTable ownership bridge.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProcessBridgeError {
    /// The managed child adapter rejected the operation.
    Managed(ManagedProcessError),
    /// A ProcessTable row or typed handle could not be found.
    TableUnavailable,
    /// The ProcessTable lifecycle transition was rejected.
    TableTransition,
    /// The ProcessTable row could not be removed during rollback or reap.
    TableReap,
}

impl From<ManagedProcessError> for ProcessBridgeError {
    fn from(error: ManagedProcessError) -> Self {
        Self::Managed(error)
    }
}

struct ProcessBinding {
    managed_handle: ProcessHandle,
    pid: u64,
    terminal_recorded: AtomicBool,
}

/// ProcessTable-authoritative child execution bridge.
pub struct ProcessTableBridge {
    managed: ManagedProcessBook,
    table: Arc<ProcessTable>,
    bindings: RwLock<HashMap<ProcessHandle, Arc<ProcessBinding>>>,
    bridge_id: u64,
    next_name: AtomicU64,
}

impl ProcessTableBridge {
    /// Construct a bridge with bounded managed-child capacity.
    pub fn new(
        config: ProcessAdapterConfig,
        max_processes: u32,
        table: Arc<ProcessTable>,
    ) -> Result<Self, ManagedProcessError> {
        Ok(Self {
            managed: ManagedProcessBook::new(config, max_processes)?,
            table,
            bindings: RwLock::new(HashMap::new()),
            bridge_id: NEXT_PROCESS_BRIDGE_ID.fetch_add(1, Ordering::Relaxed),
            next_name: AtomicU64::new(1),
        })
    }

    /// Return the number of children still owned by the bridge.
    pub fn active_count(&self) -> usize {
        self.read_bindings().len()
    }

    /// Return the ProcessTable used as the public ownership authority.
    pub fn table(&self) -> Arc<ProcessTable> {
        Arc::clone(&self.table)
    }

    /// Spawn direct arguments and register the child before it becomes running.
    pub fn spawn_args(
        &self,
        args: &[String],
        options: Option<&ProcessOptions>,
    ) -> Result<ProcessHandle, ProcessBridgeError> {
        self.spawn_registered(|managed| managed.spawn_args(args, options))
    }

    /// Write to a child identified by its ProcessTable handle.
    pub fn write_stdin(
        &self,
        handle: ProcessHandle,
        input: &[u8],
    ) -> Result<usize, ProcessBridgeError> {
        let binding = self.binding(handle)?;
        self.managed
            .write_stdin(binding.managed_handle, input)
            .map_err(Into::into)
    }

    /// Close stdin for a child identified by its ProcessTable handle.
    pub fn close_stdin(&self, handle: ProcessHandle) -> Result<(), ProcessBridgeError> {
        let binding = self.binding(handle)?;
        self.managed
            .close_stdin(binding.managed_handle)
            .map_err(Into::into)
    }

    /// Observe a child without changing ownership on timeout.
    pub fn wait(
        &self,
        handle: ProcessHandle,
        timeout: Duration,
    ) -> Result<ManagedWaitResult, ProcessBridgeError> {
        let binding = self.binding(handle)?;
        let result = self.managed.wait(binding.managed_handle, timeout)?;
        if let ManagedWaitResult::Finished(ref value) = result {
            self.record_exit(handle, &binding, value)?;
        }
        Ok(result)
    }

    /// Terminate a child and record its terminal state in ProcessTable.
    pub fn terminate(
        &self,
        handle: ProcessHandle,
        timeout: Duration,
    ) -> Result<ProcessResult, ProcessBridgeError> {
        let binding = self.binding(handle)?;
        let result = self.managed.terminate(binding.managed_handle, timeout)?;
        self.record_exit(handle, &binding, &result)?;
        Ok(result)
    }

    /// Return a cross-book snapshot for one ProcessTable-owned handle.
    pub fn snapshot(
        &self,
        handle: ProcessHandle,
    ) -> Result<ProcessBridgeSnapshot, ProcessBridgeError> {
        let binding = self.binding(handle)?;
        let managed = self.managed.snapshot(binding.managed_handle)?;
        let table = self
            .table
            .get_by_handle(handle)
            .ok_or(ProcessBridgeError::TableUnavailable)?;
        Ok(ProcessBridgeSnapshot {
            contract_version: PROCESS_BRIDGE_CONTRACT_VERSION,
            handle: handle.raw(),
            pid: binding.pid,
            table_state: table.state,
            managed_state: managed.state,
            returncode: managed.returncode,
        })
    }

    /// Reap the managed child and its ProcessTable row as one public operation.
    pub fn reap(&self, handle: ProcessHandle) -> Result<ProcessResult, ProcessBridgeError> {
        let binding = self.binding(handle)?;
        let result = match self.managed.wait(binding.managed_handle, Duration::ZERO)? {
            ManagedWaitResult::Finished(result) => result,
            ManagedWaitResult::Pending => {
                return Err(ProcessBridgeError::Managed(
                    ManagedProcessError::ProcessRunning,
                ));
            }
        };
        if let Err(error) = self.record_exit(handle, &binding, &result) {
            // The child is terminal even when another table owner won the
            // lifecycle transition. Consume the managed slot so this binding
            // cannot leak, then surface the table conflict to the caller.
            self.managed.reap(binding.managed_handle)?;
            let table_reaped = self.table.reap_handle(handle).is_some();
            self.write_bindings().remove(&handle);
            if !table_reaped {
                return Err(ProcessBridgeError::TableReap);
            }
            return Err(error);
        }
        let result = self.managed.reap(binding.managed_handle)?;
        // Once the host child is reaped, this binding cannot be retried. Drop
        // it even when an external table owner won the row-reap race.
        let table_reaped = self.table.reap_handle(handle).is_some();
        self.write_bindings().remove(&handle);
        if !table_reaped {
            return Err(ProcessBridgeError::TableReap);
        }
        Ok(result)
    }

    /// Reap all children that are already terminal without blocking on live ones.
    pub fn reap_finished(&self) -> ProcessReapReport {
        let handles = self.read_bindings().keys().copied().collect::<Vec<_>>();
        let mut report = ProcessReapReport {
            inspected: handles.len() as u64,
            ..ProcessReapReport::default()
        };
        for handle in handles {
            match self.wait(handle, Duration::ZERO) {
                Ok(ManagedWaitResult::Pending) => {
                    report.pending = report.pending.saturating_add(1);
                }
                Ok(ManagedWaitResult::Finished(_)) => match self.reap(handle) {
                    Ok(_) => report.reaped = report.reaped.saturating_add(1),
                    Err(ProcessBridgeError::TableUnavailable) => {
                        report.unavailable = report.unavailable.saturating_add(1)
                    }
                    Err(_) => report.errors = report.errors.saturating_add(1),
                },
                Err(ProcessBridgeError::TableUnavailable) => {
                    report.unavailable = report.unavailable.saturating_add(1)
                }
                Err(ProcessBridgeError::TableTransition) => match self.reap(handle) {
                    Ok(_) => report.reaped = report.reaped.saturating_add(1),
                    Err(ProcessBridgeError::TableUnavailable) => {
                        report.unavailable = report.unavailable.saturating_add(1)
                    }
                    Err(_) => report.errors = report.errors.saturating_add(1),
                },
                Err(_) => report.errors = report.errors.saturating_add(1),
            }
        }
        report
    }

    fn spawn_registered(
        &self,
        spawn: impl FnOnce(&ManagedProcessBook) -> Result<ProcessHandle, ManagedProcessError>,
    ) -> Result<ProcessHandle, ProcessBridgeError> {
        let name = format!(
            "managed-process-{}-{}",
            self.bridge_id,
            self.next_name.fetch_add(1, Ordering::Relaxed)
        );
        let pcb = self.table.spawn(name.clone(), "managed", 0, None);
        let Some(table_handle) = self.table.handle_for_pid(pcb.pid) else {
            // The table row may have been removed by another owner between
            // registration and handle lookup. Roll it back before returning.
            let _ = self.table.reap(pcb.pid);
            return Err(ProcessBridgeError::TableUnavailable);
        };
        let managed_handle = match spawn(&self.managed) {
            Ok(handle) => handle,
            Err(error) => {
                if self.table.reap_handle(table_handle).is_none() {
                    return Err(ProcessBridgeError::TableReap);
                }
                return Err(error.into());
            }
        };
        if !self.table.set_running(&name) {
            let _ = self
                .managed
                .terminate(managed_handle, PROCESS_BRIDGE_ROLLBACK_TIMEOUT);
            let _ = self.managed.reap(managed_handle);
            let _ = self.table.reap_handle(table_handle);
            return Err(ProcessBridgeError::TableTransition);
        }
        self.write_bindings().insert(
            table_handle,
            Arc::new(ProcessBinding {
                managed_handle,
                pid: pcb.pid,
                terminal_recorded: AtomicBool::new(false),
            }),
        );
        Ok(table_handle)
    }

    fn record_exit(
        &self,
        handle: ProcessHandle,
        binding: &ProcessBinding,
        result: &ProcessResult,
    ) -> Result<(), ProcessBridgeError> {
        if binding
            .terminal_recorded
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
            && !self
                .table
                .exit_handle(handle, result.returncode, "managed child exited")
        {
            binding.terminal_recorded.store(false, Ordering::Release);
            return Err(ProcessBridgeError::TableTransition);
        }
        Ok(())
    }

    fn binding(&self, handle: ProcessHandle) -> Result<Arc<ProcessBinding>, ProcessBridgeError> {
        self.read_bindings()
            .get(&handle)
            .cloned()
            .ok_or(ProcessBridgeError::TableUnavailable)
    }

    fn read_bindings(
        &self,
    ) -> std::sync::RwLockReadGuard<'_, HashMap<ProcessHandle, Arc<ProcessBinding>>> {
        self.bindings.read().unwrap_or_else(PoisonError::into_inner)
    }

    fn write_bindings(
        &self,
    ) -> std::sync::RwLockWriteGuard<'_, HashMap<ProcessHandle, Arc<ProcessBinding>>> {
        self.bindings
            .write()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl Drop for ProcessTableBridge {
    fn drop(&mut self) {
        let bindings = std::mem::take(
            self.bindings
                .get_mut()
                .unwrap_or_else(PoisonError::into_inner),
        );
        for (handle, binding) in bindings {
            if let Ok(result) = self
                .managed
                .terminate(binding.managed_handle, PROCESS_BRIDGE_ROLLBACK_TIMEOUT)
            {
                let _ = self.record_exit(handle, &binding, &result);
            }
            let _ = self.managed.reap(binding.managed_handle);
            let _ = self.table.reap_handle(handle);
        }
    }
}
