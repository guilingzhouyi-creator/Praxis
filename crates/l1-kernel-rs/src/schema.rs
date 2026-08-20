//! Thread-safe string-event schema registry candidate for the L1 kernel.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard, OnceLock, PoisonError};

use serde::{Deserialize, Serialize};

/// One owner-qualified string event description.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EventSchema {
    /// Stable event name.
    pub name: String,
    /// Subsystem that owns the event name.
    pub owner: String,
    /// Human-readable event description.
    pub description: String,
}

/// Thread-safe sorted event-schema registry.
pub struct EventSchemaRegistry {
    events: Mutex<BTreeMap<String, EventSchema>>,
}

impl EventSchemaRegistry {
    /// Create an empty schema registry.
    pub fn new() -> Self {
        Self {
            events: Mutex::new(BTreeMap::new()),
        }
    }

    /// Register an event, rejecting a name claimed by another owner.
    pub fn register_event(
        &self,
        name: impl Into<String>,
        owner: impl Into<String>,
        description: impl Into<String>,
    ) -> bool {
        let name = name.into();
        let owner = owner.into();
        let mut events = self.lock_events();
        if let Some(existing) = events.get(&name)
            && existing.owner != owner
        {
            return false;
        }
        events.insert(
            name.clone(),
            EventSchema {
                name,
                owner,
                description: description.into(),
            },
        );
        true
    }

    /// Return whether an event name is registered.
    pub fn has_event(&self, name: &str) -> bool {
        self.lock_events().contains_key(name)
    }

    /// Return a deterministic name-sorted snapshot of the catalog.
    pub fn list_events(&self) -> Vec<EventSchema> {
        self.lock_events().values().cloned().collect()
    }

    /// Clear all registrations.
    pub fn reset(&self) {
        self.lock_events().clear();
    }

    fn lock_events(&self) -> MutexGuard<'_, BTreeMap<String, EventSchema>> {
        self.events.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for EventSchemaRegistry {
    fn default() -> Self {
        Self::new()
    }
}

static GLOBAL_SCHEMA: OnceLock<Mutex<Option<Arc<EventSchemaRegistry>>>> = OnceLock::new();

fn global_schema() -> &'static Mutex<Option<Arc<EventSchemaRegistry>>> {
    GLOBAL_SCHEMA.get_or_init(|| Mutex::new(None))
}

/// Return the process-wide event schema candidate.
pub fn get_schema() -> Arc<EventSchemaRegistry> {
    let mut slot = global_schema()
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    Arc::clone(slot.get_or_insert_with(|| Arc::new(EventSchemaRegistry::new())))
}

/// Register an event on the process-wide candidate registry.
pub fn register_event(
    name: impl Into<String>,
    owner: impl Into<String>,
    description: impl Into<String>,
) -> bool {
    get_schema().register_event(name, owner, description)
}

/// Check an event on the process-wide candidate registry.
pub fn has_event(name: &str) -> bool {
    get_schema().has_event(name)
}

/// List events from the process-wide candidate registry.
pub fn list_events() -> Vec<EventSchema> {
    get_schema().list_events()
}

/// Reset the process-wide candidate registry for test isolation.
pub fn reset_event_schema() {
    *global_schema()
        .lock()
        .unwrap_or_else(PoisonError::into_inner) = None;
}

#[cfg(test)]
mod tests {
    use super::{EventSchemaRegistry, list_events, register_event, reset_event_schema};
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
            "../../../tests/fixtures/kernel_schema_vectors.json"
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
            .map(|event| super::EventSchema {
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
}
