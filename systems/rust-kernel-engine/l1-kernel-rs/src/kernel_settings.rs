//! Rust-native settings facade for the clean-break kernel.
//!
//! The facade preserves the small L1 settings surface without importing the
//! Python runtime or depending on an L3 settings implementation. A provider
//! may be injected by a future Rust host, while standalone callers use the
//! bounded in-memory defaults. Persistence, hot reload, authorization, and
//! service reconfiguration remain outside this mechanism candidate.

use std::collections::BTreeMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{
    Arc, RwLock, RwLockReadGuard, RwLockWriteGuard,
    atomic::{AtomicU64, Ordering},
};

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Maximum UTF-8 byte length accepted for one setting identity.
pub const MAX_SETTING_KEY_BYTES: usize = 256;
/// Maximum number of fallback or provider-supplied settings retained by a snapshot.
pub const MAX_SETTINGS: usize = 512;
/// Default model name retained from the Python semantic reference.
pub const DEFAULT_LLM_MODEL: &str = "codellama:7b";
/// Default provider name retained from the Python semantic reference.
pub const DEFAULT_LLM_PROVIDER: &str = "ollama";

/// Flat settings map used at the Rust/host boundary.
pub type SettingsValues = BTreeMap<String, Value>;

/// Source of a settings snapshot.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SettingsSource {
    /// The local Rust fallback is authoritative because no provider is wired.
    Fallback,
    /// An injected host provider is authoritative.
    Injected,
}

/// Defensive read model returned by the settings facade.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SettingsSnapshot {
    /// Monotonic facade revision for fallback writes or provider reports.
    pub revision: u64,
    /// Whether the values came from the local fallback or an injected provider.
    pub source: SettingsSource,
    /// Deterministically ordered setting values.
    pub values: SettingsValues,
}

/// Provider snapshot returned by an injected host implementation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProviderSnapshot {
    /// Provider-owned revision, if the host has a durable revision.
    pub revision: u64,
    /// Provider-owned setting values.
    pub values: SettingsValues,
}

/// Provider contract injected by a Rust host or a future TS/Rust adapter.
///
/// Implementations own persistence and authorization. The facade only validates
/// identities, selects the provider, and returns defensive snapshots.
pub trait SettingsProvider: Send + Sync {
    /// Read the provider's complete settings view.
    fn snapshot(&self) -> Result<ProviderSnapshot, String>;

    /// Set one runtime setting.
    fn set(&self, key: &str, value: Value) -> Result<(), String>;

    /// Set one L2/configuration-layer setting.
    fn set_l2(&self, key: &str, value: Value) -> Result<(), String> {
        self.set(key, value)
    }

    /// Set a group of settings under the provider's own atomicity policy.
    fn set_many(&self, values: &SettingsValues) -> Result<(), String>;

    /// Reset one setting to the provider's configured default.
    fn reset(&self, key: &str) -> Result<(), String>;

    /// Reset all provider settings to their configured defaults.
    fn reset_all(&self) -> Result<(), String>;
}

/// Structured settings admission or provider failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettingsError {
    /// A setting key is empty, contains NUL, or exceeds the identity bound.
    InvalidKey(String),
    /// A snapshot exceeds the bounded settings count.
    TooManySettings(usize),
    /// A provider returned an invalid key/value map.
    InvalidProviderSnapshot(String),
    /// The injected provider rejected an operation.
    Provider(String),
}

impl std::fmt::Display for SettingsError {
    /// Render a stable settings error.
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidKey(key) => write!(formatter, "setting key is invalid: {key:?}"),
            Self::TooManySettings(count) => {
                write!(
                    formatter,
                    "settings count {count} exceeds limit {MAX_SETTINGS}"
                )
            }
            Self::InvalidProviderSnapshot(message) => {
                write!(
                    formatter,
                    "provider settings snapshot is invalid: {message}"
                )
            }
            Self::Provider(message) => write!(formatter, "settings provider failed: {message}"),
        }
    }
}

impl std::error::Error for SettingsError {}

/// Rust-native settings facade with an injected-provider seam and safe fallback.
pub struct SettingsRegistry {
    defaults: SettingsValues,
    fallback: RwLock<SettingsValues>,
    provider: RwLock<Option<Arc<dyn SettingsProvider>>>,
    fallback_revision: AtomicU64,
}

impl SettingsRegistry {
    /// Create a registry populated with the Rust-owned semantic defaults.
    pub fn new() -> Self {
        Self::with_defaults(default_values()).expect("built-in settings defaults are valid")
    }

    /// Create a registry with caller-supplied fallback defaults.
    ///
    /// # Errors
    ///
    /// Returns an identity/count error before any registry is created.
    pub fn with_defaults(defaults: SettingsValues) -> Result<Self, SettingsError> {
        validate_values(&defaults)?;
        Ok(Self {
            fallback: RwLock::new(defaults.clone()),
            defaults,
            provider: RwLock::new(None),
            fallback_revision: AtomicU64::new(0),
        })
    }

    /// Attach a provider after validating its initial snapshot.
    ///
    /// The provider is not made visible when its snapshot is malformed.
    pub fn set_provider(
        &self,
        provider: Arc<dyn SettingsProvider>,
    ) -> Result<SettingsSnapshot, SettingsError> {
        let snapshot = provider_snapshot(&provider)?;
        *write_lock(&self.provider) = Some(provider);
        Ok(SettingsSnapshot {
            revision: snapshot.revision,
            source: SettingsSource::Injected,
            values: snapshot.values,
        })
    }

    /// Detach the provider and restore the local fallback to its defaults.
    pub fn clear_provider(&self) {
        *write_lock(&self.provider) = None;
        *write_lock(&self.fallback) = self.defaults.clone();
        self.fallback_revision.store(0, Ordering::Release);
    }

    /// Return a complete defensive settings snapshot.
    pub fn snapshot(&self) -> Result<SettingsSnapshot, SettingsError> {
        if let Some(provider) = self.provider() {
            let snapshot = provider_snapshot(&provider)?;
            return Ok(SettingsSnapshot {
                revision: snapshot.revision,
                source: SettingsSource::Injected,
                values: snapshot.values,
            });
        }
        Ok(SettingsSnapshot {
            revision: self.fallback_revision.load(Ordering::Acquire),
            source: SettingsSource::Fallback,
            values: read_lock(&self.fallback).clone(),
        })
    }

    /// Return one setting, or `None` when it is absent.
    pub fn get(&self, key: &str) -> Result<Option<Value>, SettingsError> {
        validate_key(key)?;
        Ok(self.snapshot()?.values.get(key).cloned())
    }

    /// Return one setting with a caller-supplied fallback value.
    pub fn get_or(&self, key: &str, default: Value) -> Result<Value, SettingsError> {
        Ok(self.get(key)?.unwrap_or(default))
    }

    /// Return every setting as a defensive copy.
    pub fn all(&self) -> Result<SettingsValues, SettingsError> {
        Ok(self.snapshot()?.values)
    }

    /// Return all values whose key starts with `prefix`.
    pub fn category(&self, prefix: &str) -> Result<SettingsValues, SettingsError> {
        validate_prefix(prefix)?;
        Ok(self
            .snapshot()?
            .values
            .into_iter()
            .filter(|(key, _)| key.starts_with(prefix))
            .collect())
    }

    /// Set one runtime setting.
    pub fn set(&self, key: &str, value: Value) -> Result<SettingsSnapshot, SettingsError> {
        validate_key(key)?;
        if let Some(provider) = self.provider() {
            provider_call("set", || provider.set(key, value))?;
            return self.snapshot();
        }
        self.set_fallback(key, value)
    }

    /// Set one L2/configuration-layer setting.
    pub fn set_l2(&self, key: &str, value: Value) -> Result<SettingsSnapshot, SettingsError> {
        validate_key(key)?;
        if let Some(provider) = self.provider() {
            provider_call("set_l2", || provider.set_l2(key, value))?;
            return self.snapshot();
        }
        self.set_fallback(key, value)
    }

    /// Set several fallback settings transactionally or delegate the group to a provider.
    pub fn set_many(&self, values: SettingsValues) -> Result<SettingsSnapshot, SettingsError> {
        validate_values(&values)?;
        if let Some(provider) = self.provider() {
            provider_call("set_many", || provider.set_many(&values))?;
            return self.snapshot();
        }
        let mut fallback = write_lock(&self.fallback);
        let mut staged = fallback.clone();
        staged.extend(values);
        validate_values(&staged)?;
        *fallback = staged;
        self.fallback_revision.fetch_add(1, Ordering::AcqRel);
        drop(fallback);
        self.snapshot()
    }

    /// Reset one setting to its default, or remove an unknown key.
    pub fn reset(&self, key: &str) -> Result<SettingsSnapshot, SettingsError> {
        validate_key(key)?;
        if let Some(provider) = self.provider() {
            provider_call("reset", || provider.reset(key))?;
            return self.snapshot();
        }
        let mut fallback = write_lock(&self.fallback);
        match self.defaults.get(key) {
            Some(default) => {
                fallback.insert(key.to_owned(), default.clone());
            }
            None => {
                fallback.remove(key);
            }
        }
        self.fallback_revision.fetch_add(1, Ordering::AcqRel);
        drop(fallback);
        self.snapshot()
    }

    /// Reset every setting to the configured defaults.
    pub fn reset_all(&self) -> Result<SettingsSnapshot, SettingsError> {
        if let Some(provider) = self.provider() {
            provider_call("reset_all", || provider.reset_all())?;
            return self.snapshot();
        }
        *write_lock(&self.fallback) = self.defaults.clone();
        self.fallback_revision.fetch_add(1, Ordering::AcqRel);
        self.snapshot()
    }

    /// Return whether one prompt injection domain is enabled.
    ///
    /// Any malformed or unavailable settings path keeps the safety-preserving
    /// default enabled, matching the Python semantic reference.
    pub fn prompt_injection_enabled(&self, domain: &str) -> bool {
        let key = format!("prompt.inject.{domain}");
        self.get(&key)
            .ok()
            .flatten()
            .and_then(|value| value.as_bool())
            .unwrap_or(true)
    }

    fn provider(&self) -> Option<Arc<dyn SettingsProvider>> {
        read_lock(&self.provider).as_ref().map(Arc::clone)
    }

    fn set_fallback(&self, key: &str, value: Value) -> Result<SettingsSnapshot, SettingsError> {
        let mut fallback = write_lock(&self.fallback);
        let mut staged = fallback.clone();
        staged.insert(key.to_owned(), value);
        validate_values(&staged)?;
        *fallback = staged;
        self.fallback_revision.fetch_add(1, Ordering::AcqRel);
        drop(fallback);
        self.snapshot()
    }
}

impl Default for SettingsRegistry {
    fn default() -> Self {
        Self::new()
    }
}

/// Return the Rust-owned fallback defaults.
pub fn default_values() -> SettingsValues {
    let mut values = SettingsValues::new();
    values.insert("l1.kernel.allocator.tokens".to_owned(), Value::from(4096));
    values.insert("l1.kernel.allocator.ring1".to_owned(), Value::from(32));
    values.insert("l1.kernel.allocator.ring2".to_owned(), Value::from(200));
    values.insert("l1.kernel.swapper.interval".to_owned(), Value::from(30.0));
    values.insert("l1.kernel.syscall.audit_max".to_owned(), Value::from(5000));
    values.insert("cell.terminal.workers".to_owned(), Value::from(4));
    values.insert("cell.terminal.poll".to_owned(), Value::from(0.05));
    values.insert("cell.card.timeout".to_owned(), Value::from(30.0));
    values.insert("llm.provider".to_owned(), Value::from(DEFAULT_LLM_PROVIDER));
    values.insert("llm.model".to_owned(), Value::from(DEFAULT_LLM_MODEL));
    values.insert("llm.max_tokens".to_owned(), Value::from(2048));
    values.insert("llm.temperature".to_owned(), Value::from(0.3));
    values.insert("llm.rate_limit".to_owned(), Value::from(10));
    values.insert("device.rate_limit_default".to_owned(), Value::from(10));
    values.insert("device.health_check_interval".to_owned(), Value::from(60.0));
    values.insert("persistence.enabled".to_owned(), Value::from(true));
    values.insert("persistence.interval".to_owned(), Value::from(30.0));
    values.insert("memory.graph.enabled".to_owned(), Value::from(false));
    values.insert("memory.mer.enabled".to_owned(), Value::from(false));
    values.insert(
        "memory.compaction_mode".to_owned(),
        Value::from("deterministic"),
    );
    values.insert("memory.premise_guard".to_owned(), Value::from(true));
    values.insert("memory.inject_dedup".to_owned(), Value::from(true));
    values.insert("user_profile.enabled".to_owned(), Value::from(false));
    for domain in [
        "profile",
        "constitution",
        "skills",
        "verification",
        "memory",
        "identity",
    ] {
        values.insert(format!("prompt.inject.{domain}"), Value::from(true));
    }
    values.insert("departments.enabled".to_owned(), Value::from(false));
    values.insert("l3a.secretary.enabled".to_owned(), Value::from(true));
    values.insert("l3a.digest.enabled".to_owned(), Value::from(true));
    values.insert("l3a.digest.max_chars".to_owned(), Value::from(400));
    values.insert("l3a.tool_result.enabled".to_owned(), Value::from(true));
    values.insert("l3a.tool_result.max_chars".to_owned(), Value::from(4000));
    values.insert("l3a.sensitive.enabled".to_owned(), Value::from(true));
    values.insert("l3a.sensitive.action".to_owned(), Value::from("report"));
    values.insert(
        "l3a.compression_guard.recursion_threshold".to_owned(),
        Value::from(0),
    );
    values.insert(
        "l3a.compression_guard.breaker_enabled".to_owned(),
        Value::from(true),
    );
    for (key, value) in [
        ("ci.review.enabled", true),
        ("ci.review.auto_trigger", true),
        ("ci.review.llm_review", false),
        ("ci.review.escalate_reject", false),
        ("ci.review.route_convention", false),
        ("ci.review.reputation", false),
        ("ci.review.lean_trace", false),
        ("ci.review.todo_linkage", false),
        ("ci.review.consume_auto_test_cache", true),
        ("ci.review.notify.enabled", false),
        ("ci.control.api.writable", true),
        ("ci.control.shell.writable", true),
        ("shells.enabled", true),
        ("engineering_debug.marker_required", true),
        ("engineering_debug.verbose_logging", true),
        ("engineering_debug.prompt_monitor", true),
        ("engineering_debug.input.enabled", false),
        ("engineering_debug.input.capture_content", false),
    ] {
        values.insert(key.to_owned(), Value::from(value));
    }
    values.insert("shells.default".to_owned(), Value::from("terminal"));
    values.insert("engineering_debug.mode".to_owned(), Value::from("auto"));
    values.insert(
        "engineering_debug.marker_file".to_owned(),
        Value::from(".praxis/debug_mode.flag"),
    );
    values
}

fn provider_snapshot(
    provider: &Arc<dyn SettingsProvider>,
) -> Result<ProviderSnapshot, SettingsError> {
    let snapshot = catch_unwind(AssertUnwindSafe(|| provider.snapshot()))
        .map_err(|_| SettingsError::Provider("provider panicked during snapshot".to_owned()))?
        .map_err(SettingsError::Provider)?;
    validate_values(&snapshot.values)
        .map_err(|error| SettingsError::InvalidProviderSnapshot(error.to_string()))?;
    Ok(snapshot)
}

fn provider_call<F>(operation: &str, function: F) -> Result<(), SettingsError>
where
    F: FnOnce() -> Result<(), String>,
{
    catch_unwind(AssertUnwindSafe(function))
        .map_err(|_| SettingsError::Provider(format!("provider panicked during {operation}")))?
        .map_err(SettingsError::Provider)
}

fn validate_values(values: &SettingsValues) -> Result<(), SettingsError> {
    if values.len() > MAX_SETTINGS {
        return Err(SettingsError::TooManySettings(values.len()));
    }
    for key in values.keys() {
        validate_key(key)?;
    }
    Ok(())
}

fn validate_key(key: &str) -> Result<(), SettingsError> {
    if key.trim().is_empty() || key.contains('\0') || key.len() > MAX_SETTING_KEY_BYTES {
        return Err(SettingsError::InvalidKey(key.to_owned()));
    }
    Ok(())
}

fn validate_prefix(prefix: &str) -> Result<(), SettingsError> {
    if prefix.contains('\0') || prefix.len() > MAX_SETTING_KEY_BYTES {
        return Err(SettingsError::InvalidKey(prefix.to_owned()));
    }
    Ok(())
}

fn read_lock<T>(lock: &RwLock<T>) -> RwLockReadGuard<'_, T> {
    lock.read().unwrap_or_else(|error| error.into_inner())
}

fn write_lock<T>(lock: &RwLock<T>) -> RwLockWriteGuard<'_, T> {
    lock.write().unwrap_or_else(|error| error.into_inner())
}
