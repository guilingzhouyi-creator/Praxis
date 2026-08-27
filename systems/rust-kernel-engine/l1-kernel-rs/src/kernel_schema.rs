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
