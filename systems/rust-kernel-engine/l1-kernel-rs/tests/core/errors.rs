//! Independent structured-error tests for the Rust kernel.

use l1_kernel_rs::errors::{ErrorCatalog, KernelError, TraceContext};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct ErrorVector {
    code: String,
    #[serde(default)]
    message: String,
    #[serde(default)]
    cause: String,
    #[serde(default)]
    context: serde_json::Map<String, serde_json::Value>,
    #[serde(default)]
    trace_id: String,
    expected_response: serde_json::Value,
    expected_trace_id: String,
}

#[test]
fn built_in_catalog_and_unknown_fallback_match_python() {
    let catalog = ErrorCatalog::builtin();
    assert_eq!(catalog.entries.len(), 20);
    assert_eq!(catalog.get("E_TIMEOUT"), Some("Operation timed out"));
    assert_eq!(
        KernelError::from_catalog(&catalog, "E_CUSTOM", "").message,
        "Unknown error: E_CUSTOM"
    );
    let mut custom = catalog.clone();
    custom.register("E_CUSTOM", "Custom failure");
    assert_eq!(
        KernelError::from_catalog(&custom, "E_CUSTOM", "").message,
        "Custom failure"
    );
}

#[test]
fn trace_context_only_propagates_explicit_ids() {
    let error = KernelError::new("E_TIMEOUT", "");
    assert!(!TraceContext::default().is_set());
    assert_eq!(
        TraceContext::new("trace-1").propagate(error).trace_id,
        "trace-1"
    );
    let existing = KernelError::new("E_INTERNAL", "").with_trace_id("existing");
    assert_eq!(
        TraceContext::new("outer").propagate(existing).trace_id,
        "existing"
    );
}

#[test]
fn shared_error_vectors_match_python_response_shape() {
    let vectors: Vec<ErrorVector> = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_error_vectors.json"
    ))
    .expect("error fixture must be valid JSON");
    let catalog = ErrorCatalog::builtin();
    for vector in vectors {
        let mut error = KernelError::from_catalog(&catalog, vector.code, vector.message)
            .with_cause(vector.cause)
            .with_trace_id(vector.trace_id);
        for (key, value) in vector.context {
            error = error.with_context(key, value);
        }
        assert_eq!(
            serde_json::to_value(error.to_response()).expect("error response serializes"),
            vector.expected_response
        );
        assert_eq!(error.trace_id, vector.expected_trace_id);
    }
}
