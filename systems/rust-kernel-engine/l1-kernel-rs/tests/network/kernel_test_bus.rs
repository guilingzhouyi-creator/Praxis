//! Independent SystemBus metadata and dependency-plan tests for the Rust kernel.

use std::collections::BTreeMap;

use l1_kernel_rs::bus::{BusPlanError, ComponentRegistry, ComponentSpec};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct BusVector {
    registrations: Vec<ComponentSpec>,
    available: Vec<String>,
    expected_names: Vec<String>,
    expected_graph: BTreeMap<String, Vec<String>>,
    expected_order: Option<Vec<String>>,
    expected_cycle: Option<Vec<String>>,
    expected_specs: Option<BTreeMap<String, ComponentSpec>>,
    expected_states: Option<BTreeMap<String, String>>,
}

#[test]
fn state_transitions_are_explicit() {
    let registry = ComponentRegistry::new();
    registry
        .register(ComponentSpec {
            name: "x".to_owned(),
            ..ComponentSpec::default()
        })
        .expect("component registers");
    assert!(registry.mark_inited("x"));
    assert!(registry.mark_started("x"));
    assert!(registry.mark_stopped("x"));
    assert!(!registry.mark_inited("x"));
    assert!(!registry.mark_started("x"));
    assert_eq!(registry.state_map()["x"], "stopped");
}

#[test]
fn registration_rejects_blank_and_nul_names() {
    let registry = ComponentRegistry::new();
    assert_eq!(
        registry.register(ComponentSpec {
            name: "   ".to_owned(),
            ..ComponentSpec::default()
        }),
        Err(BusPlanError::EmptyName)
    );
    assert_eq!(
        registry.register(ComponentSpec {
            name: "bad\0name".to_owned(),
            ..ComponentSpec::default()
        }),
        Err(BusPlanError::InvalidName)
    );
    assert!(registry.names().is_empty());
}

#[test]
fn replacement_uses_index_without_changing_registration_order() {
    let registry = ComponentRegistry::new();
    registry
        .register(ComponentSpec {
            name: "first".to_owned(),
            version: "1.0.0".to_owned(),
            ..ComponentSpec::default()
        })
        .expect("first registers");
    registry
        .register(ComponentSpec {
            name: "second".to_owned(),
            ..ComponentSpec::default()
        })
        .expect("second registers");

    registry
        .register(ComponentSpec {
            name: "first".to_owned(),
            version: "2.0.0".to_owned(),
            description: "replacement".to_owned(),
            ..ComponentSpec::default()
        })
        .expect("replacement registers");

    assert_eq!(registry.names(), ["first", "second"]);
    assert_eq!(
        registry.get("first"),
        Some(ComponentSpec {
            name: "first".to_owned(),
            version: "2.0.0".to_owned(),
            description: "replacement".to_owned(),
            ..ComponentSpec::default()
        })
    );
}

#[test]
fn duplicate_dependency_declarations_are_one_graph_edge() {
    let registry = ComponentRegistry::new();
    registry
        .register(ComponentSpec {
            name: "base".to_owned(),
            ..ComponentSpec::default()
        })
        .expect("base registers");
    registry
        .register(ComponentSpec {
            name: "consumer".to_owned(),
            depends_on: vec!["base".to_owned()],
            optional_deps: vec!["base".to_owned()],
            ..ComponentSpec::default()
        })
        .expect("consumer registers");

    let plan = registry.plan(&[]).expect("duplicate edge is harmless");
    assert_eq!(plan.graph["consumer"], ["base", "base"]);
    assert_eq!(plan.order, ["base", "consumer"]);
}

#[test]
fn shared_bus_vectors_match_python_reference() {
    let vectors: Vec<BusVector> = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_bus_vectors.json"
    ))
    .expect("bus fixture must be valid JSON");
    for vector in vectors {
        let registry = ComponentRegistry::new();
        for spec in vector.registrations {
            registry
                .register(spec)
                .expect("fixture metadata must be valid");
        }
        assert_eq!(registry.names(), vector.expected_names);
        let plan = registry.plan(&vector.available);
        if let Some(expected_cycle) = vector.expected_cycle {
            assert_eq!(plan, Err(BusPlanError::Cycle(expected_cycle)));
            continue;
        }
        let plan = plan.expect("acyclic fixture must plan");
        assert_eq!(plan.graph, vector.expected_graph);
        assert_eq!(plan.order, vector.expected_order.expect("order"));
        for name in registry.names() {
            assert!(registry.mark_inited(&name));
            assert!(registry.mark_started(&name));
            assert!(registry.mark_stopped(&name));
        }
        assert_eq!(
            registry.state_map(),
            vector.expected_states.expect("states")
        );
        if let Some(expected_specs) = vector.expected_specs {
            for (name, expected) in expected_specs {
                assert_eq!(registry.get(&name), Some(expected));
            }
        }
    }
}
