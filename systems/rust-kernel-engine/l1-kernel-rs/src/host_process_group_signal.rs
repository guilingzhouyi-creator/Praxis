//! Host-owned process-group stop adapter for the Rust L1 boundary.
//!
//! The kernel emits generation-safe member handles, while a host resolves
//! those handles to opaque process-group or PTY targets and performs the
//! platform operation. This adapter intentionally does not select a signal,
//! inspect the host, or retain process objects. Resolution happens before the
//! sender is called so a missing target cannot create a partial dispatch.

use std::collections::BTreeSet;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Arc;

use crate::process_group::{
    PROCESS_GROUP_CONTRACT_VERSION, PROCESS_GROUP_SIGNAL_CONTRACT_VERSION, ProcessGroupSignalPort,
    ProcessGroupSignalReport, ProcessGroupTerminationPlan,
};

/// Version of the closure-backed host signal adapter contract.
pub const HOST_PROCESS_GROUP_SIGNAL_CONTRACT_VERSION: u32 = 1;

type TargetResolver = dyn Fn(u64) -> Result<u64, String> + Send + Sync;
type StopSender = dyn Fn(&[u64]) -> Result<u64, String> + Send + Sync;

/// A host adapter that resolves Rust handles and sends one bounded stop batch.
///
/// The resolver maps each generation-safe Rust handle to a host-owned opaque
/// target. The sender receives targets in the exact stable plan order and
/// returns the number of accepted operations. A sender may implement a Unix
/// process-group signal, a Windows job/console operation, a PTY control frame,
/// or a test double without changing the L1 contract.
pub struct HostProcessGroupSignalPort {
    resolver: Arc<TargetResolver>,
    sender: Arc<StopSender>,
}

impl HostProcessGroupSignalPort {
    /// Construct an adapter from explicit host target resolution and dispatch.
    pub fn new<R, S>(resolver: R, sender: S) -> Self
    where
        R: Fn(u64) -> Result<u64, String> + Send + Sync + 'static,
        S: Fn(&[u64]) -> Result<u64, String> + Send + Sync + 'static,
    {
        Self {
            resolver: Arc::new(resolver),
            sender: Arc::new(sender),
        }
    }
}

impl ProcessGroupSignalPort for HostProcessGroupSignalPort {
    fn send_stop(
        &self,
        plan: &ProcessGroupTerminationPlan,
    ) -> Result<ProcessGroupSignalReport, String> {
        validate_plan(plan)?;
        let mut targets = Vec::with_capacity(plan.handles.len());
        for handle in &plan.handles {
            let target = catch_unwind(AssertUnwindSafe(|| (self.resolver)(*handle)))
                .map_err(|_| format!("host target resolution panicked for {handle}"))?
                .map_err(|error| format!("host target resolution failed for {handle}: {error}"))?;
            if target == 0 {
                return Err(format!("host target resolution returned zero for {handle}"));
            }
            targets.push(target);
        }
        let delivered = catch_unwind(AssertUnwindSafe(|| (self.sender)(&targets)))
            .map_err(|_| "host stop sender panicked".to_owned())??;
        if delivered > targets.len() as u64 {
            return Err("host sender returned more deliveries than targets".to_owned());
        }
        Ok(ProcessGroupSignalReport {
            contract_version: PROCESS_GROUP_SIGNAL_CONTRACT_VERSION,
            group_id: plan.group_id,
            generation: plan.generation,
            attempted: plan.handles.len() as u64,
            delivered,
        })
    }
}

/// Validate a termination plan fail-closed before signaling.
fn validate_plan(plan: &ProcessGroupTerminationPlan) -> Result<(), String> {
    if plan.contract_version != PROCESS_GROUP_CONTRACT_VERSION {
        return Err("unsupported process-group plan contract".to_owned());
    }
    if plan.group_id == 0 {
        return Err("process-group plan has an invalid group id".to_owned());
    }
    if plan.generation == 0 {
        return Err("process-group plan has an invalid generation".to_owned());
    }
    let mut handles = BTreeSet::new();
    for handle in &plan.handles {
        if *handle == 0 || !handles.insert(*handle) {
            return Err("process-group plan handles must be non-zero and unique".to_owned());
        }
    }
    Ok(())
}
