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
fn shared_bus_vectors_match_python_reference() {
    let vectors: Vec<BusVector> = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_bus_vectors.json"
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
