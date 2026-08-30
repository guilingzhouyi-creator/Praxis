//! Rust-owned settings provider backed by the clean-break configuration store.
//!
//! The adapter is the explicit bridge between semantic settings operations and
//! the Rust-owned JSON root. It does not import Python configuration or decide
//! authorization; those responsibilities remain with the host that owns the
//! provider and with the future versioned API/L2 adapter.

use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use serde_json::Value;

use crate::config_store::ConfigStore;
use crate::settings::{ProviderSnapshot, SettingsProvider, SettingsValues, default_values};

/// Provider that persists settings into one Rust-owned [`ConfigStore`].
///
/// The provider overlays persisted values on the semantic Rust defaults so a
/// fresh persistent root has the same read surface as an in-memory registry.
/// The persisted document remains sparse: defaults are not written until a
/// caller explicitly mutates or resets the setting.
pub struct ConfigStoreSettingsProvider {
    store: Arc<Mutex<ConfigStore>>,
    defaults: SettingsValues,
}

impl ConfigStoreSettingsProvider {
    /// Build a provider using the Rust-native default catalog.
    pub fn new(store: Arc<Mutex<ConfigStore>>) -> Self {
        Self::with_defaults(store, default_values())
    }

    /// Build a provider with an explicit default catalog.
    ///
    /// The caller is responsible for validating custom defaults through
    /// [`crate::settings::SettingsRegistry::with_defaults`] before injection.
    pub fn with_defaults(store: Arc<Mutex<ConfigStore>>, defaults: SettingsValues) -> Self {
        Self { store, defaults }
    }

    /// Return the shared store handle used by this provider.
    pub fn store(&self) -> Arc<Mutex<ConfigStore>> {
        Arc::clone(&self.store)
    }

    fn lock_store(&self) -> MutexGuard<'_, ConfigStore> {
        self.store.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn merged_values(&self, persisted: &SettingsValues) -> SettingsValues {
        let mut values = self.defaults.clone();
        values.extend(persisted.clone());
        values
    }
}

impl SettingsProvider for ConfigStoreSettingsProvider {
    /// Read a defensive snapshot with semantic defaults overlaid.
    fn snapshot(&self) -> Result<ProviderSnapshot, String> {
        let store = self.lock_store();
        Ok(ProviderSnapshot {
            revision: store.settings().revision,
            values: self.merged_values(&store.settings().values),
        })
    }

    /// Persist one setting and publish it on the next snapshot.
    fn set(&self, key: &str, value: Value) -> Result<(), String> {
        self.lock_store()
            .set_setting(key.to_owned(), value)
            .map_err(|error| error.to_string())
    }

    /// Persist one L2/configuration-layer setting.
    fn set_l2(&self, key: &str, value: Value) -> Result<(), String> {
        self.set(key, value)
    }

    /// Persist a group of settings as one document replacement.
    fn set_many(&self, values: &SettingsValues) -> Result<(), String> {
        self.lock_store()
            .set_settings(values)
            .map_err(|error| error.to_string())
    }

    /// Restore one default, or remove an unknown setting.
    fn reset(&self, key: &str) -> Result<(), String> {
        self.lock_store()
            .reset_setting(key, self.defaults.get(key).cloned())
            .map_err(|error| error.to_string())
    }

    /// Restore the complete semantic default catalog.
    fn reset_all(&self) -> Result<(), String> {
        self.lock_store()
            .replace_settings(self.defaults.clone())
            .map_err(|error| error.to_string())
    }
}
