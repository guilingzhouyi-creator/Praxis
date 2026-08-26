//! Independent event-schema registry tests for the Rust kernel.

use l1_kernel_rs::schema::{
    EventSchema, EventSchemaRegistry, list_events, register_event, reset_event_schema,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct SchemaVector {
    registrations: Vec<Registration>,
    expected: Vec<ExpectedEvent>,
    has: Vec<String>,
    missing: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct Registration {
    name: String,
    owner: String,
    description: String,
}

#[derive(Debug, Deserialize)]
struct ExpectedEvent {
    name: String,
    owner: String,
    description: String,
}

#[test]
fn owner_conflicts_are_rejected_and_same_owner_updates() {
    let registry = EventSchemaRegistry::new();
    assert!(registry.register_event("dup.event", "owner-a", "first"));
    assert!(!registry.register_event("dup.event", "owner-b", "blocked"));
    assert!(registry.register_event("dup.event", "owner-a", "updated"));
    assert_eq!(registry.list_events()[0].description, "updated");
}

#[test]
fn shared_schema_vectors_match_python_reference() {
    let vector: SchemaVector = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_schema_vectors.json"
    ))
    .expect("schema fixture must be valid JSON");
    let registry = EventSchemaRegistry::new();
    for registration in vector.registrations {
        assert!(registry.register_event(
            registration.name,
            registration.owner,
            registration.description
        ));
    }
    let expected = vector
        .expected
        .into_iter()
        .map(|event| EventSchema {
            name: event.name,
            owner: event.owner,
            description: event.description,
        })
        .collect::<Vec<_>>();
    assert_eq!(registry.list_events(), expected);
    for name in vector.has {
        assert!(registry.has_event(&name));
    }
    for name in vector.missing {
        assert!(!registry.has_event(&name));
    }
}

#[test]
fn global_schema_can_be_reset() {
    reset_event_schema();
    assert!(register_event("global.event", "test", ""));
    assert_eq!(list_events().len(), 1);
    reset_event_schema();
    assert!(list_events().is_empty());
}
