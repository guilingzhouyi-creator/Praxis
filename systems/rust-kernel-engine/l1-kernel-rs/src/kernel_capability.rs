//! Rust candidate for the single capability execution authority.

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};

use crate::audit::AuditLog;
use crate::contract::{CapabilityRequest, CapabilityResult};

/// Executor callback accepted by the capability authority.
pub type CapabilityExecutor =
    Arc<dyn Fn(CapabilityRequest) -> CapabilityResult + Send + Sync + 'static>;

/// One fail-closed capability authority with an injectable executor and audit trail.
pub struct CapabilityAuthority {
    executor: Mutex<Option<CapabilityExecutor>>,
    audit: Arc<AuditLog>,
}

impl CapabilityAuthority {
    /// Create an unwired authority.
    pub fn new() -> Self {
        Self {
            executor: Mutex::new(None),
            audit: Arc::new(AuditLog::new()),
        }
    }

    /// Create an authority using a caller-owned audit trail.
    pub fn with_audit(audit: Arc<AuditLog>) -> Self {
        Self {
            executor: Mutex::new(None),
            audit,
        }
    }

    /// Wire one executor; boot adapters are the intended caller.
    pub fn register_executor<F>(&self, executor: F)
    where
        F: Fn(CapabilityRequest) -> CapabilityResult + Send + Sync + 'static,
    {
        *self.executor.lock().unwrap_or_else(PoisonError::into_inner) = Some(Arc::new(executor));
    }

    /// Register an already type-erased executor supplied by a bootstrapper.
    pub fn register_executor_arc(&self, executor: CapabilityExecutor) {
        *self.executor.lock().unwrap_or_else(PoisonError::into_inner) = Some(executor);
    }

    /// Remove the executor for shutdown or test isolation.
    pub fn reset_executor(&self) {
        *self.executor.lock().unwrap_or_else(PoisonError::into_inner) = None;
    }

    /// Return whether an executor is currently wired.
    pub fn has_executor(&self) -> bool {
        self.executor
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .is_some()
    }

    /// Return the authority's audit trail.
    pub fn audit(&self) -> Arc<AuditLog> {
        Arc::clone(&self.audit)
    }

    /// Invoke exactly one wired executor, auditing every accepted or denied call.
    ///
    /// This seam never panics and never propagates an `Err`: every outcome
    /// folds into the returned [`CapabilityResult`] and is written to the
    /// bounded audit log before the caller observes it.
    ///
    /// # Errors
    ///
    /// Encoded in the result rather than thrown:
    /// - no executor wired → fail-closed `unwired` denial (audited);
    /// - executor panic → caught via `catch_unwind`, surfaced as
    ///   `success=false` with error `"capability executor panicked"`.
    pub fn invoke(&self, request: CapabilityRequest) -> CapabilityResult {
        let executor = self
            .executor
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone();
        let name = request.name.clone();
        let agent_id = request.agent_id.clone();
        let result = match executor {
            None => CapabilityResult::unwired(name.clone()),
            Some(executor) => match catch_unwind(AssertUnwindSafe(|| executor(request))) {
                Ok(mut result) => {
                    if result.capability.is_empty() {
                        result.capability = name.clone();
                    }
                    result
                }
                Err(_) => CapabilityResult {
                    success: false,
                    error: "capability executor panicked".to_owned(),
                    capability: name.clone(),
                    data: Default::default(),
                },
            },
        };
        self.audit.record_fields(
            "capability.invoke",
            agent_id,
            result.success,
            result.error.clone(),
            result.capability.clone(),
        );
        result
    }
}

impl Default for CapabilityAuthority {
    /// Create an empty capability authority.
    fn default() -> Self {
        Self::new()
    }
}

static GLOBAL_AUTHORITY: OnceLock<Mutex<Option<Arc<CapabilityAuthority>>>> = OnceLock::new();

/// Initialize the process-wide authority slot on first use.
fn global_authority() -> &'static Mutex<Option<Arc<CapabilityAuthority>>> {
    GLOBAL_AUTHORITY.get_or_init(|| Mutex::new(None))
}

/// Return the process-global capability authority.
pub fn get_capability_authority() -> Arc<CapabilityAuthority> {
    let mut authority = global_authority()
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    Arc::clone(authority.get_or_insert_with(|| Arc::new(CapabilityAuthority::new())))
}

/// Reset the global authority for tests or a controlled restart.
pub fn reset_capability_authority() {
    *global_authority()
        .lock()
        .unwrap_or_else(PoisonError::into_inner) = None;
}
