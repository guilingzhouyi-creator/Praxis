//! Independent configuration-discovery mechanism tests for the Rust kernel.

use l1_kernel_rs::discovery::{
    DiscoveryDocument, DiscoveryError, DiscoveryRegistry, DiscoverySnapshot,
    MAX_DISCOVERY_IDENTITY_BYTES,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

#[derive(Debug, Deserialize)]
struct DiscoveryVector {
    defaults: Map<String, Value>,
    overrides: Map<String, Value>,
    expected_config: Map<String, Value>,
    expected_source: Map<String, Value>,
    tool_queries: Vec<QueryVector>,
    service_queries: Vec<QueryVector>,
}

#[derive(Debug, Deserialize)]
struct QueryVector {
    key: String,
    default: Value,
    expected: Value,
}

#[test]
fn merge_and_runtime_override_preserve_three_tier_shape() {
    let registry = DiscoveryRegistry::new();
    registry.register("tool", json!({"git_timeout": 30, "shell_timeout": 10}));
    registry.register("scalar", json!("default"));
    assert!(registry.set_config("tool", "git_timeout", json!(45)));
    assert_eq!(registry.get_tool_config("git_timeout", json!(0)), json!(45));
    assert!(!registry.set_config("scalar", "key", json!(1)));
    registry.reset();
    assert_eq!(registry.get_tool_config("git_timeout", json!(0)), json!(30));
}

#[test]
fn null_sections_keep_defaults_and_unknown_sections_are_ignored() {
    let registry = DiscoveryRegistry::new();
    registry.register("tool", json!({"timeout": 30}));
    let document = DiscoveryDocument {
        sections: [
            ("tool".to_owned(), json!(null)),
            ("unknown".to_owned(), json!({"dead": true})),
        ]
        .into_iter()
        .collect(),
    };
    assert_eq!(registry.apply_document(&document), 1);
    assert_eq!(
        registry.get_config("tool", json!({})),
        json!({"timeout": 30})
    );
}

#[test]
fn shared_discovery_vectors_match_python_reference() {
    let vectors: Vec<DiscoveryVector> = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_discovery_vectors.json"
    ))
    .expect("discovery fixture must be valid JSON");
    for vector in vectors {
        let registry = DiscoveryRegistry::new();
        for (name, defaults) in vector.defaults {
            registry.register(name, defaults);
        }
        registry.apply_document(&DiscoveryDocument {
            sections: vector.overrides.into_iter().collect(),
        });
        for (name, expected) in vector.expected_config {
            assert_eq!(
                registry.get_config(&name, Value::Null),
                expected,
                "config {name}"
            );
        }
        for (name, expected) in vector.expected_source {
            assert_eq!(
                registry.get_source(&name, Value::Null),
                expected,
                "source {name}"
            );
        }
        for query in vector.tool_queries {
            assert_eq!(
                registry.get_tool_config(&query.key, query.default),
                query.expected,
                "tool {}",
                query.key
            );
        }
        for query in vector.service_queries {
            assert_eq!(
                registry.get_service_limit(&query.key, query.default),
                query.expected,
                "service {}",
                query.key
            );
        }
    }
}

#[test]
fn invalid_registration_is_rejected_without_state_mutation() {
    let registry = DiscoveryRegistry::new();
    assert!(!registry.register(" ", json!({"timeout": 30})));
    assert!(!registry.register("tool\0", json!({"timeout": 30})));
    assert!(!registry.register("x".repeat(MAX_DISCOVERY_IDENTITY_BYTES + 1), json!({})));
    assert_eq!(registry.sections(), Vec::<String>::new());

    let error = registry
        .try_register("tool", json!({"bad\0key": true}))
        .expect_err("invalid nested key must fail closed");
    assert!(matches!(error, DiscoveryError::InvalidObjectKey(key) if key == "bad\0key"));
    assert_eq!(registry.snapshot(), DiscoverySnapshot::default());
}

#[test]
fn invalid_document_is_transactional_and_preserves_previous_override() {
    let registry = DiscoveryRegistry::new();
    registry
        .try_register("tool", json!({"timeout": 30, "mode": "safe"}))
        .expect("register");
    registry
        .try_apply_document(&DiscoveryDocument {
            sections: [("tool".to_owned(), json!({"timeout": 45}))]
                .into_iter()
                .collect(),
        })
        .expect("valid document");

    let invalid = DiscoveryDocument {
        sections: [
            ("tool".to_owned(), json!({"mode": "debug"})),
            ("bad\0section".to_owned(), json!({"ignored": true})),
        ]
        .into_iter()
        .collect(),
    };
    let error = registry
        .try_apply_document(&invalid)
        .expect_err("invalid section must reject the whole document");
    assert!(matches!(error, DiscoveryError::InvalidSection(section) if section == "bad\0section"));
    assert_eq!(
        registry.get_config("tool", Value::Null),
        json!({"timeout": 45, "mode": "safe"})
    );
}

#[test]
fn runtime_identity_and_shape_errors_are_explicit() {
    let registry = DiscoveryRegistry::new();
    registry
        .try_register("scalar", json!("default"))
        .expect("register scalar");
    let error = registry
        .try_set_config("scalar", "key", json!(1))
        .expect_err("scalar section cannot receive object key");
    assert!(matches!(
        error,
        DiscoveryError::NonObjectSection(section) if section == "scalar"
    ));

    let error = registry
        .try_set_config("tool", " ", json!(1))
        .expect_err("blank key must fail closed");
    assert!(matches!(error, DiscoveryError::InvalidKey(key) if key == " "));
    assert!(!registry.set_config("tool\0", "key", json!(1)));
}

#[test]
fn snapshot_is_deterministic_and_reset_restores_sources() {
    let registry = DiscoveryRegistry::new();
    registry
        .try_register("zeta", json!({"z": 1}))
        .expect("register zeta");
    registry
        .try_register("alpha", json!({"a": 1}))
        .expect("register alpha");
    registry
        .try_set_config("zeta", "z", json!(2))
        .expect("runtime override");

    assert_eq!(
        registry.sections(),
        vec!["alpha".to_owned(), "zeta".to_owned()]
    );
    let snapshot = registry.snapshot();
    assert_eq!(snapshot.sources["zeta"], json!({"z": 1}));
    assert_eq!(snapshot.registry["zeta"], json!({"z": 2}));
    registry.reset();
    assert_eq!(registry.snapshot().registry, snapshot.sources);
}
