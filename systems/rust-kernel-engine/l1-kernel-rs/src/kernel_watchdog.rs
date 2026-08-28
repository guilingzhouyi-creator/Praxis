//! Provider-neutral watchdog evaluation for the Rust L1 kernel.
//!
//! The evaluator mirrors the observation semantics of Python's `os.py`
//! watchdog without owning a thread, a clock, a ProcessTable, or an interrupt
//! singleton. Hosts provide one bounded observation slice and decide whether
//! to log, interrupt, drain, or restart after reviewing the report.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::contract::ProcessState;

/// Version of the watchdog observation/report contract.
pub const WATCHDOG_CONTRACT_VERSION: u32 = 1;
/// Reference zombie threshold from the Python prototype.
pub const REFERENCE_WATCHDOG_ZOMBIE_LIMIT: u64 = 50;
/// Reference idle threshold in milliseconds from the Python prototype.
pub const REFERENCE_WATCHDOG_IDLE_LIMIT_MS: u64 = 300_000;
/// Reference interrupt threshold from the Python prototype.
pub const REFERENCE_WATCHDOG_INTERRUPT_LIMIT: u64 = 1_000;

/// Explicit watchdog thresholds selected by the host.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct WatchdogPolicy {
    /// Emit a zombie alert when the count is strictly above this limit.
    pub zombie_limit: u64,
    /// Report ready/running processes idle for strictly longer than this.
    pub idle_limit_ms: u64,
    /// Report an interrupt kind whose count is strictly above this limit.
    pub interrupt_limit: u64,
}

impl WatchdogPolicy {
    /// Build a validated watchdog policy.
    ///
    /// Zero thresholds are rejected because they turn a bounded diagnostic
    /// policy into an always-alerting policy and usually indicate a missing
    /// deployment value.
    pub fn new(
        zombie_limit: u64,
        idle_limit_ms: u64,
        interrupt_limit: u64,
    ) -> Result<Self, WatchdogPolicyError> {
        if zombie_limit == 0 {
            return Err(WatchdogPolicyError::ZeroZombieLimit);
        }
        if idle_limit_ms == 0 {
            return Err(WatchdogPolicyError::ZeroIdleLimit);
        }
        if interrupt_limit == 0 {
            return Err(WatchdogPolicyError::ZeroInterruptLimit);
        }
        Ok(Self {
            zombie_limit,
            idle_limit_ms,
            interrupt_limit,
        })
    }

    /// Return the explicit reference values used by the Python prototype.
    pub const fn reference() -> Self {
        Self {
            zombie_limit: REFERENCE_WATCHDOG_ZOMBIE_LIMIT,
            idle_limit_ms: REFERENCE_WATCHDOG_IDLE_LIMIT_MS,
            interrupt_limit: REFERENCE_WATCHDOG_INTERRUPT_LIMIT,
        }
    }
}

/// Invalid watchdog deployment values.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WatchdogPolicyError {
    /// A zero zombie limit would alert on every non-empty observation.
    ZeroZombieLimit,
    /// A zero idle limit would alert on every ready/running process.
    ZeroIdleLimit,
    /// A zero interrupt limit would alert on every recorded interrupt.
    ZeroInterruptLimit,
}

impl std::fmt::Display for WatchdogPolicyError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::ZeroZombieLimit => "zombie_limit must be greater than zero",
            Self::ZeroIdleLimit => "idle_limit_ms must be greater than zero",
            Self::ZeroInterruptLimit => "interrupt_limit must be greater than zero",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for WatchdogPolicyError {}

/// One host-supplied process observation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WatchdogProcess {
    /// Stable process or agent identity.
    pub pid: u64,
    /// Process lifecycle state observed by the host.
    pub state: ProcessState,
    /// Caller-computed idle duration in milliseconds.
    pub idle_ms: u64,
}

impl WatchdogProcess {
    /// Build one process observation without reading a clock.
    pub const fn new(pid: u64, state: ProcessState, idle_ms: u64) -> Self {
        Self {
            pid,
            state,
            idle_ms,
        }
    }
}

/// One process that exceeded the configured idle threshold.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IdleProcess {
    /// Stable process or agent identity.
    pub pid: u64,
    /// Observed idle duration in milliseconds.
    pub idle_ms: u64,
}

/// One interrupt kind that exceeded the configured burst threshold.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterruptAlert {
    /// Stable interrupt kind spelling supplied by the host.
    pub kind: String,
    /// Observed count for this kind.
    pub count: u64,
}

/// Result of one bounded watchdog observation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WatchdogReport {
    /// Watchdog contract version.
    pub contract_version: u32,
    /// Number of processes inspected.
    pub process_count: usize,
    /// Number of zombie processes observed.
    pub zombie_count: u64,
    /// Whether the zombie count is strictly above the policy limit.
    pub zombie_limit_exceeded: bool,
    /// Ready/running processes that exceeded the idle threshold, in input order.
    pub idle_processes: Vec<IdleProcess>,
    /// Interrupt kinds above the threshold, in deterministic key order.
    pub interrupt_alerts: Vec<InterruptAlert>,
}

impl WatchdogReport {
    /// Return whether this observation requires host-owned follow-up.
    pub fn has_alerts(&self) -> bool {
        self.zombie_limit_exceeded
            || !self.idle_processes.is_empty()
            || !self.interrupt_alerts.is_empty()
    }

    /// Return the total number of alert records in this report.
    pub fn alert_count(&self) -> usize {
        usize::from(self.zombie_limit_exceeded)
            .saturating_add(self.idle_processes.len())
            .saturating_add(self.interrupt_alerts.len())
    }
}

/// Evaluate one process and interrupt observation slice in one bounded pass.
///
/// The process loop intentionally combines zombie counting and idle detection,
/// matching Python's single-pass watchdog tick. Interrupt counts are traversed
/// in the caller's `BTreeMap` order so reports remain deterministic without
/// requiring a second sort or any shared mutable state.
pub fn evaluate_watchdog(
    policy: WatchdogPolicy,
    processes: &[WatchdogProcess],
    interrupts: &BTreeMap<String, u64>,
) -> WatchdogReport {
    let mut zombie_count = 0_u64;
    let mut idle_processes = Vec::new();
    for process in processes {
        if process.state == ProcessState::Zombie {
            zombie_count = zombie_count.saturating_add(1);
        } else if matches!(process.state, ProcessState::Ready | ProcessState::Running)
            && process.idle_ms > policy.idle_limit_ms
        {
            idle_processes.push(IdleProcess {
                pid: process.pid,
                idle_ms: process.idle_ms,
            });
        }
    }

    let interrupt_alerts = interrupts
        .iter()
        .filter(|(_, count)| **count > policy.interrupt_limit)
        .map(|(kind, count)| InterruptAlert {
            kind: kind.clone(),
            count: *count,
        })
        .collect();

    WatchdogReport {
        contract_version: WATCHDOG_CONTRACT_VERSION,
        process_count: processes.len(),
        zombie_count,
        zombie_limit_exceeded: zombie_count > policy.zombie_limit,
        idle_processes,
        interrupt_alerts,
    }
}
