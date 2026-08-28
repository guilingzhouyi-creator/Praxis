//! Provider-neutral declarative configuration discovery values.

use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Maximum accepted UTF-8 byte length for a discovery section or key.
pub const MAX_DISCOVERY_IDENTITY_BYTES: usize = 256;

/// A parsed discovery document supplied by the Python/YAML adapter.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct DiscoveryDocument {
    /// Top-level section name to override value.
    #[serde(flatten)]
    pub sections: BTreeMap<String, Value>,
}

/// A deterministic read-only view of all registered discovery state.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct DiscoverySnapshot {
    /// Original defaults keyed by section name.
    pub sources: BTreeMap<String, Value>,
    /// Current merged/runtime values keyed by section name.
    pub registry: BTreeMap<String, Value>,
}

/// Structured failure for configuration-discovery admission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DiscoveryError {
    /// A section identity is empty, contains NUL, or exceeds the bound.
    InvalidSection(String),
    /// A runtime or object key is empty, contains NUL, or exceeds the bound.
    InvalidKey(String),
    /// A JSON object contains a key outside the accepted identity boundary.
    InvalidObjectKey(String),
    /// A runtime update targeted a registered scalar/list section.
    NonObjectSection(String),
}

impl std::fmt::Display for DiscoveryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidSection(section) => {
                write!(
                    formatter,
                    "discovery section identity is invalid: {section:?}"
                )
            }
            Self::InvalidKey(key) => {
                write!(formatter, "discovery runtime key is invalid: {key:?}")
            }
            Self::InvalidObjectKey(key) => {
                write!(formatter, "discovery object key is invalid: {key:?}")
            }
            Self::NonObjectSection(section) => {
                write!(formatter, "discovery section is not an object: {section:?}")
            }
        }
    }
}

impl std::error::Error for DiscoveryError {}

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
    ///
    /// Invalid identities are rejected without mutating the registry. The
    /// boolean return keeps the original infallible adapter-facing shape;
    /// callers that need the reason should use [`Self::try_register`].
    pub fn register(&self, name: impl Into<String>, defaults: Value) -> bool {
        self.try_register(name, defaults).is_ok()
    }

    /// Register defaults with an explicit admission error.
    pub fn try_register(
        &self,
        name: impl Into<String>,
        defaults: Value,
    ) -> Result<(), DiscoveryError> {
        let name = name.into();
        validate_section(&name)?;
        validate_value_keys(&defaults)?;
        let mut state = self.lock();
        state.sources.insert(name.clone(), defaults.clone());
        state.registry.insert(name, defaults);
        Ok(())
    }

    /// Apply parsed YAML values and return the number of registered sections applied.
    ///
    /// Unknown sections are ignored. A null value keeps the registered defaults,
    /// matching Python `discover()`'s empty-section rule.
    pub fn apply_document(&self, document: &DiscoveryDocument) -> usize {
        self.try_apply_document(document).unwrap_or(0)
    }

    /// Apply one document transactionally with an explicit admission error.
    ///
    /// Every section and object key is validated before a staged registry copy
    /// is committed. This prevents a malformed later section from leaving
    /// earlier overrides visible.
    pub fn try_apply_document(
        &self,
        document: &DiscoveryDocument,
    ) -> Result<usize, DiscoveryError> {
        for (section, override_value) in &document.sections {
            validate_section(section)?;
            validate_value_keys(override_value)?;
        }
        let mut state = self.lock();
        let mut staged = state.registry.clone();
        let mut applied = 0;
        for (section, override_value) in &document.sections {
            let Some(current) = staged.get_mut(section) else {
                continue;
            };
            if override_value.is_null() {
                applied += 1;
                continue;
            }
            merge_value(current, override_value);
            applied += 1;
        }
        state.registry = staged;
        Ok(applied)
    }

    /// Return the merged section or an adapter-supplied fallback.
    pub fn get_config(&self, name: &str, default: Value) -> Value {
        self.lock().registry.get(name).cloned().unwrap_or(default)
    }

    /// Read a merged section with explicit identity validation.
    pub fn try_get_config(&self, name: &str, default: Value) -> Result<Value, DiscoveryError> {
        validate_section(name)?;
        Ok(self.get_config(name, default))
    }

    /// Report whether a validated section is currently registered.
    pub fn has_section(&self, name: &str) -> Result<bool, DiscoveryError> {
        validate_section(name)?;
        Ok(self.lock().registry.contains_key(name))
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
        self.try_set_config(name, key, value).is_ok()
    }

    /// Set one runtime override with explicit identity and shape errors.
    pub fn try_set_config(
        &self,
        name: impl Into<String>,
        key: impl Into<String>,
        value: Value,
    ) -> Result<(), DiscoveryError> {
        let name = name.into();
        let key = key.into();
        validate_section(&name)?;
        validate_key(&key)?;
        validate_value_keys(&value)?;
        let mut state = self.lock();
        let section = state
            .registry
            .entry(name.clone())
            .or_insert_with(|| Value::Object(Map::new()));
        let Value::Object(section) = section else {
            return Err(DiscoveryError::NonObjectSection(name));
        };
        section.insert(key, value);
        Ok(())
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

    /// Return a deterministic copy of source and merged state.
    pub fn snapshot(&self) -> DiscoverySnapshot {
        let state = self.lock();
        DiscoverySnapshot {
            sources: state.sources.clone(),
            registry: state.registry.clone(),
        }
    }

    /// Return all registered section names in deterministic order.
    pub fn sections(&self) -> Vec<String> {
        self.lock().registry.keys().cloned().collect()
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

fn merge_value(current: &mut Value, override_value: &Value) {
    if let (Some(current_map), Some(overrides)) =
        (current.as_object_mut(), override_value.as_object())
    {
        for (key, value) in overrides {
            current_map.insert(key.clone(), value.clone());
        }
        return;
    }
    *current = override_value.clone();
}

fn validate_section(section: &str) -> Result<(), DiscoveryError> {
    if !valid_identity(section) {
        return Err(DiscoveryError::InvalidSection(section.to_owned()));
    }
    Ok(())
}

fn validate_key(key: &str) -> Result<(), DiscoveryError> {
    if !valid_identity(key) {
        return Err(DiscoveryError::InvalidKey(key.to_owned()));
    }
    Ok(())
}

fn validate_value_keys(value: &Value) -> Result<(), DiscoveryError> {
    let Value::Object(values) = value else {
        return Ok(());
    };
    for (key, nested) in values {
        if !valid_identity(key) {
            return Err(DiscoveryError::InvalidObjectKey(key.clone()));
        }
        validate_value_keys(nested)?;
    }
    Ok(())
}

fn valid_identity(identity: &str) -> bool {
    !identity.trim().is_empty()
        && !identity.contains('\0')
        && identity.len() <= MAX_DISCOVERY_IDENTITY_BYTES
}
