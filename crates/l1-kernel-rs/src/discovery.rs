//! Provider-neutral declarative configuration discovery values.

use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// A parsed discovery document supplied by the Python/YAML adapter.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct DiscoveryDocument {
    /// Top-level section name to override value.
    #[serde(flatten)]
    pub sections: BTreeMap<String, Value>,
}

/// Thread-safe three-tier discovery registry.
pub struct DiscoveryRegistry {
    state: Mutex<DiscoveryState>,
}

#[derive(Debug, Default)]
struct DiscoveryState {
    sources: BTreeMap<String, Value>,
    registry: BTreeMap<String, Value>,
}

impl DiscoveryRegistry {
    /// Create an empty registry.
    pub const fn new() -> Self {
        Self {
            state: Mutex::new(DiscoveryState {
                sources: BTreeMap::new(),
                registry: BTreeMap::new(),
            }),
        }
    }

    /// Register defaults and reset the current section to that value.
    pub fn register(&self, name: impl Into<String>, defaults: Value) {
        let name = name.into();
        let mut state = self.lock();
        state.sources.insert(name.clone(), defaults.clone());
        state.registry.insert(name, defaults);
    }

    /// Apply parsed YAML values and return the number of registered sections applied.
    ///
    /// Unknown sections are ignored. A null value keeps the registered defaults,
    /// matching Python `discover()`'s empty-section rule.
    pub fn apply_document(&self, document: &DiscoveryDocument) -> usize {
        let mut state = self.lock();
        let mut applied = 0;
        for (section, override_value) in &document.sections {
            let Some(current) = state.registry.get_mut(section) else {
                continue;
            };
            if override_value.is_null() {
                applied += 1;
                continue;
            }
            merge_value(current, override_value.clone());
            applied += 1;
        }
        applied
    }

    /// Return the merged section or an adapter-supplied fallback.
    pub fn get_config(&self, name: &str, default: Value) -> Value {
        self.lock().registry.get(name).cloned().unwrap_or(default)
    }

    /// Return the originally registered defaults for a section.
    pub fn get_source(&self, name: &str, default: Value) -> Value {
        self.lock().sources.get(name).cloned().unwrap_or(default)
    }

    /// Set one runtime override and return whether the section accepted it.
    pub fn set_config(
        &self,
        name: impl Into<String>,
        key: impl Into<String>,
        value: Value,
    ) -> bool {
        let mut state = self.lock();
        let section = state
            .registry
            .entry(name.into())
            .or_insert_with(|| Value::Object(Map::new()));
        let Value::Object(section) = section else {
            return false;
        };
        section.insert(key.into(), value);
        true
    }

    /// Read a tool setting, falling back to an injected params value.
    pub fn get_tool_config(&self, key: &str, default: Value) -> Value {
        self.get_section_key("tool", key, default)
    }

    /// Read a service limit, falling back to an injected params value.
    pub fn get_service_limit(&self, key: &str, default: Value) -> Value {
        self.get_section_key("service_limits", key, default)
    }

    /// Restore every registered section to its original defaults.
    pub fn reset(&self) {
        let mut state = self.lock();
        state.registry = state.sources.clone();
    }

    fn get_section_key(&self, section: &str, key: &str, default: Value) -> Value {
        let state = self.lock();
        state
            .registry
            .get(section)
            .and_then(Value::as_object)
            .and_then(|values| values.get(key))
            .cloned()
            .unwrap_or(default)
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, DiscoveryState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for DiscoveryRegistry {
    fn default() -> Self {
        Self::new()
    }
}

fn merge_value(current: &mut Value, override_value: Value) {
    if current.is_object() && override_value.is_object() {
        let overrides = override_value.as_object().expect("object checked above");
        let current_map = current.as_object_mut().expect("object checked above");
        for (key, value) in overrides {
            current_map.insert(key.clone(), value.clone());
        }
        return;
    }
    *current = override_value;
}

#[cfg(test)]
mod tests {
    use serde::Deserialize;
    use serde_json::{Map, Value, json};

    use super::{DiscoveryDocument, DiscoveryRegistry};

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
            let document = DiscoveryDocument {
                sections: vector.overrides.into_iter().collect(),
            };
            registry.apply_document(&document);
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
}
