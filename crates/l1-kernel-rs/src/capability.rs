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
    fn default() -> Self {
        Self::new()
    }
}

static GLOBAL_AUTHORITY: OnceLock<Mutex<Option<Arc<CapabilityAuthority>>>> = OnceLock::new();

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

#[cfg(test)]
mod tests {
    use super::{CapabilityAuthority, get_capability_authority, reset_capability_authority};
    use crate::contract::{CapabilityRequest, CapabilityResult, JsonObject, JsonValue};
    use std::collections::BTreeMap;
    use std::sync::Arc;

    fn request() -> CapabilityRequest {
        CapabilityRequest {
            agent_id: "agent-a".to_owned(),
            name: "read_file".to_owned(),
            args: JsonObject::from([("path".to_owned(), JsonValue::String("/tmp/x".to_owned()))]),
            domain: "d".to_owned(),
            nature: "n".to_owned(),
            interactive: true,
        }
    }

    #[test]
    fn unwired_invocation_fails_closed_and_is_audited() {
        let authority = CapabilityAuthority::new();
        let result = authority.invoke(request());
        assert!(!result.success);
        assert!(result.error.contains("fail-closed"));
        let rows = authority.audit().query(10, Some("agent-a"));
        assert_eq!(rows.len(), 1);
        assert!(!rows[0].success);
    }

    #[test]
    fn wired_executor_receives_request_and_audits_result() {
        let authority = CapabilityAuthority::new();
        authority.register_executor(|request| CapabilityResult {
            success: true,
            error: String::new(),
            capability: request.name,
            data: JsonObject::from([(
                "result".to_owned(),
                JsonValue::Object(BTreeMap::from([("ok".to_owned(), JsonValue::Bool(true))])),
            )]),
        });
        let result = authority.invoke(request());
        assert!(result.success);
        assert_eq!(
            result.data["result"],
            JsonValue::Object(BTreeMap::from([("ok".to_owned(), JsonValue::Bool(true))]))
        );
        assert!(authority.audit().query(10, Some("agent-a"))[0].success);
    }

    #[test]
    fn executor_failure_and_panic_are_structured() {
        let authority = CapabilityAuthority::new();
        authority.register_executor(|_| CapabilityResult {
            success: false,
            error: "nope".to_owned(),
            capability: String::new(),
            data: Default::default(),
        });
        let failed = authority.invoke(request());
        assert_eq!(failed.error, "nope");
        authority.register_executor(|_| panic!("boom"));
        let panicked = authority.invoke(request());
        assert_eq!(panicked.error, "capability executor panicked");
    }

    #[test]
    fn global_authority_can_be_reset() {
        let first = get_capability_authority();
        first.register_executor(|_| CapabilityResult::unwired("x"));
        reset_capability_authority();
        assert!(!get_capability_authority().has_executor());
        let _ = Arc::strong_count(&first);
    }
}
