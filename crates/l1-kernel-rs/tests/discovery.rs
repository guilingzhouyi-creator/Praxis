//! Independent configuration-discovery mechanism tests for the Rust kernel.

use l1_kernel_rs::discovery::{DiscoveryDocument, DiscoveryRegistry};
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
        "../../../tests/fixtures/kernel_discovery_vectors.json"
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
