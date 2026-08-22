//! Thread-safe metadata registry candidate for the L1 kernel.
//!
//! The candidate mirrors the value and lifecycle rules of Python's
//! `registry_base.MapRegistry`. Handler closures and domain-specific policy
//! remain adapter-owned; only declarative metadata crosses this boundary.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};

const DESCRIPTION_LIMIT: usize = 200;

fn empty_metadata() -> Map<String, Value> {
    Map::new()
}

/// Declarative metadata for one registrable entity.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegisterableSpec {
    /// Unique identifier within one registry.
    pub name: String,
    /// Human-readable description.
    #[serde(default)]
    pub description: String,
    /// Grouping key used by category filters.
    #[serde(default = "default_category")]
    pub category: String,
    /// Arbitrary tags used by upper-layer discovery.
    #[serde(default)]
    pub tags: Vec<String>,
    /// Opaque metadata retained for the adapter, not exposed by `to_dict`.
    #[serde(default = "empty_metadata")]
    pub metadata: Map<String, Value>,
    /// Semantic version of this descriptor.
    #[serde(default = "default_version")]
    pub version: String,
}

fn default_category() -> String {
    "other".to_owned()
}

fn default_version() -> String {
    "1.0.0".to_owned()
}

impl RegisterableSpec {
    /// Build a descriptor with Python-compatible defaults.
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: String::new(),
            category: default_category(),
            tags: Vec::new(),
            metadata: empty_metadata(),
            version: default_version(),
        }
    }

    /// Return the public descriptor view, excluding handlers and metadata.
    pub fn to_dict(&self) -> Value {
        json!({
            "name": self.name,
            "description": self.description.chars().take(DESCRIPTION_LIMIT).collect::<String>(),
            "category": self.category,
            "tags": self.tags,
            "version": self.version,
        })
    }
}

/// Aggregate counters exposed by a registry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegistryStats {
    /// Number of entries currently registered.
    pub total: usize,
    /// Number of successful registrations, including overwrites.
    pub registers: usize,
    /// Number of successful removals.
    pub unregisters: usize,
    /// Current entry count grouped by category.
    pub categories: BTreeMap<String, usize>,
}

#[derive(Debug, Default)]
struct RegistryState {
    items: Vec<RegisterableSpec>,
    registers: usize,
    unregisters: usize,
}

type RegisterCallback = Arc<dyn Fn(String, RegisterableSpec) + Send + Sync>;
type UnregisterCallback = Arc<dyn Fn(String) + Send + Sync>;

/// Thread-safe ordered registry for declarative descriptors.
pub struct MapRegistry {
    allow_overwrite: bool,
    state: Mutex<RegistryState>,
    on_register: Mutex<Option<RegisterCallback>>,
    on_unregister: Mutex<Option<UnregisterCallback>>,
}

impl MapRegistry {
    /// Create an empty registry with an explicit overwrite policy.
    pub fn new(allow_overwrite: bool) -> Self {
        Self {
            allow_overwrite,
            state: Mutex::new(RegistryState::default()),
            on_register: Mutex::new(None),
            on_unregister: Mutex::new(None),
        }
    }

    /// Install an optional local callback invoked after successful registration.
    pub fn set_on_register<F>(&self, callback: F)
    where
        F: Fn(String, RegisterableSpec) + Send + Sync + 'static,
    {
        *self
            .on_register
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = Some(Arc::new(callback));
    }

    /// Install an optional local callback invoked after successful removal.
    pub fn set_on_unregister<F>(&self, callback: F)
    where
        F: Fn(String) + Send + Sync + 'static,
    {
        *self
            .on_unregister
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = Some(Arc::new(callback));
    }

    /// Register a descriptor, rejecting duplicates unless overwrite is enabled.
    pub fn register(&self, spec: RegisterableSpec, _source: &str) -> bool {
        let callback = {
            let mut state = self.lock_state();
            if let Some(index) = state.items.iter().position(|item| item.name == spec.name) {
                if !self.allow_overwrite {
                    return false;
                }
                state.items[index] = spec.clone();
            } else {
                state.items.push(spec.clone());
            }
            state.registers += 1;
            self.lock_register_callback().clone()
        };
        if let Some(callback) = callback {
            callback(spec.name.clone(), spec);
        }
        true
    }

    /// Remove a descriptor by name and report whether it existed.
    pub fn unregister(&self, name: &str) -> bool {
        let callback = {
            let mut state = self.lock_state();
            let Some(index) = state.items.iter().position(|item| item.name == name) else {
                return false;
            };
            state.items.remove(index);
            state.unregisters += 1;
            self.lock_unregister_callback().clone()
        };
        if let Some(callback) = callback {
            callback(name.to_owned());
        }
        true
    }

    /// Return a cloned descriptor for a name, if present.
    pub fn get(&self, name: &str) -> Option<RegisterableSpec> {
        self.lock_state()
            .items
            .iter()
            .find(|item| item.name == name)
            .cloned()
    }

    /// Return descriptors in registration order, optionally filtered by category.
    pub fn list_items(&self, category: &str) -> Vec<RegisterableSpec> {
        self.lock_state()
            .items
            .iter()
            .filter(|item| category.is_empty() || item.category == category)
            .cloned()
            .collect()
    }

    /// Return names in registration order.
    pub fn all_names(&self) -> Vec<String> {
        self.lock_state()
            .items
            .iter()
            .map(|item| item.name.clone())
            .collect()
    }

    /// Return counters and current category membership.
    pub fn stats(&self) -> RegistryStats {
        let state = self.lock_state();
        let mut categories = BTreeMap::new();
        for item in &state.items {
            *categories.entry(item.category.clone()).or_insert(0) += 1;
        }
        RegistryStats {
            total: state.items.len(),
            registers: state.registers,
            unregisters: state.unregisters,
            categories,
        }
    }

    /// Remove all descriptors and return the number removed.
    pub fn clear(&self) -> usize {
        let mut state = self.lock_state();
        let count = state.items.len();
        state.items.clear();
        count
    }

    fn lock_state(&self) -> MutexGuard<'_, RegistryState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_register_callback(&self) -> MutexGuard<'_, Option<RegisterCallback>> {
        self.on_register
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_unregister_callback(&self) -> MutexGuard<'_, Option<UnregisterCallback>> {
        self.on_unregister
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for MapRegistry {
    fn default() -> Self {
        Self::new(false)
    }
}
