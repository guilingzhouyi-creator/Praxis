//! Deterministic device bookkeeping candidate for the L1 kernel.
//!
//! External connections, SettingsCenter defaults, health threads, and provider
//! calls remain Python-owned. This module accepts device records and explicit
//! timestamps, then mirrors rate-window and health-threshold mechanics.

use std::collections::BTreeMap;
use std::sync::{Mutex, MutexGuard, PoisonError};

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

const HEALTHY: &str = "HEALTHY";
const DEGRADED: &str = "DEGRADED";
const DOWN: &str = "DOWN";

/// Injected health policy and stable device-type inventory.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DeviceConfig {
    /// Error ratio strictly above this value marks a device degraded.
    pub degraded_threshold: f64,
    /// Error ratio strictly above this value marks a device down.
    pub down_threshold: f64,
    /// Minimum calls strictly above which degraded status can be assigned.
    pub min_calls_degraded: u64,
    /// Minimum calls strictly above which down status can be assigned.
    pub min_calls_down: u64,
    /// Device types included in aggregate statistics.
    pub type_names: Vec<String>,
    /// Decimal places used for rate-window reset values.
    pub reset_precision: u32,
}

/// One provider-neutral device record.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DeviceRecord {
    /// Stable device name.
    pub name: String,
    /// Built-in or caller-defined type name.
    pub device_type: String,
    /// Current health label.
    #[serde(default = "default_health")]
    pub health: String,
    /// Maximum calls in one rate window.
    pub rate_limit: u64,
    /// Sliding-window duration in seconds.
    pub rate_window: f64,
    /// Human-readable description.
    #[serde(default)]
    pub description: String,
    /// Capability names supplied by the adapter.
    #[serde(default)]
    pub capabilities: Vec<String>,
    /// Caller-supplied connection timestamp.
    #[serde(default)]
    pub connected_at: f64,
    /// Last explicit call timestamp.
    #[serde(default)]
    pub last_used: f64,
    /// Number of recorded calls.
    #[serde(default)]
    pub call_count: u64,
    /// Number of failed calls.
    #[serde(default)]
    pub error_count: u64,
    /// Adapter/provider version.
    #[serde(default)]
    pub version: String,
}

fn default_health() -> String {
    HEALTHY.to_owned()
}

#[derive(Debug, Default)]
struct DeviceState {
    devices: BTreeMap<String, DeviceRecord>,
    call_timestamps: BTreeMap<String, Vec<f64>>,
}

/// Thread-safe device table with explicit-time rate and health mechanics.
pub struct DeviceTable {
    config: DeviceConfig,
    state: Mutex<DeviceState>,
}

impl DeviceTable {
    /// Create an empty table from injected health thresholds and type names.
    pub fn new(config: DeviceConfig) -> Self {
        Self {
            config,
            state: Mutex::new(DeviceState::default()),
        }
    }

    /// Register a device, rejecting duplicate names.
    pub fn register(&self, device: DeviceRecord) -> bool {
        let mut state = self.lock_state();
        if state.devices.contains_key(&device.name) {
            return false;
        }
        state
            .call_timestamps
            .insert(device.name.clone(), Vec::new());
        state.devices.insert(device.name.clone(), device);
        true
    }

    /// Return a cloned device record, if present.
    pub fn get(&self, name: &str) -> Option<DeviceRecord> {
        self.lock_state().devices.get(name).cloned()
    }

    /// Record one call at an explicit timestamp.
    pub fn record_call(&self, name: &str, success: bool, now: f64) -> bool {
        let mut state = self.lock_state();
        {
            let Some(device) = state.devices.get_mut(name) else {
                return false;
            };
            device.last_used = now;
            device.call_count = device.call_count.saturating_add(1);
            if !success {
                device.error_count = device.error_count.saturating_add(1);
            }
        }
        state
            .call_timestamps
            .entry(name.to_owned())
            .or_default()
            .push(now);
        true
    }

    /// Check the sliding rate window at an explicit timestamp.
    pub fn check_rate(&self, name: &str, now: f64) -> Value {
        let mut state = self.lock_state();
        let Some((rate_limit, rate_window)) = state
            .devices
            .get(name)
            .map(|device| (device.rate_limit, device.rate_window))
        else {
            return json!({"allowed": false, "error": format!("unknown device: {name}")});
        };
        let timestamps = state.call_timestamps.entry(name.to_owned()).or_default();
        let cutoff = now - rate_window;
        timestamps.retain(|timestamp| *timestamp > cutoff);
        let remaining = rate_limit.saturating_sub(timestamps.len() as u64);
        if remaining == 0 {
            let reset_after = timestamps
                .first()
                .map(|timestamp| round(*timestamp + rate_window - now, self.config.reset_precision))
                .unwrap_or(0.0);
            return json!({"allowed": false, "remaining": 0, "reset_after": reset_after});
        }
        json!({"allowed": true, "remaining": remaining, "reset_after": 0})
    }

    /// Re-evaluate all device health labels using strict Python thresholds.
    pub fn refresh_health(&self) {
        let mut state = self.lock_state();
        for device in state.devices.values_mut() {
            let calls = device.call_count as f64;
            let errors = device.error_count as f64;
            if errors > calls * self.config.degraded_threshold
                && device.call_count > self.config.min_calls_degraded
            {
                device.health = DEGRADED.to_owned();
            }
            if errors > calls * self.config.down_threshold
                && device.call_count > self.config.min_calls_down
            {
                device.health = DOWN.to_owned();
            }
        }
    }

    /// Set a health label, returning false for an unknown device.
    pub fn set_health(&self, name: &str, health: impl Into<String>) -> bool {
        let mut state = self.lock_state();
        let Some(device) = state.devices.get_mut(name) else {
            return false;
        };
        device.health = health.into();
        true
    }

    /// Return Python-compatible public summaries, optionally filtered by type.
    pub fn list(&self, device_type: Option<&str>) -> Vec<Value> {
        self.lock_state()
            .devices
            .values()
            .filter(|device| device_type.is_none_or(|kind| device.device_type == kind))
            .map(summary)
            .collect()
    }

    /// Return aggregate counts and configured type buckets.
    pub fn stats(&self) -> Value {
        let state = self.lock_state();
        let mut by_type = self
            .config
            .type_names
            .iter()
            .map(|kind| (kind.clone(), 0_u64))
            .collect::<BTreeMap<_, _>>();
        for device in state.devices.values() {
            *by_type.entry(device.device_type.clone()).or_default() += 1;
        }
        json!({
            "total_devices": state.devices.len(),
            "by_type": by_type,
            "healthy": state.devices.values().filter(|d| d.health == HEALTHY).count(),
            "down": state.devices.values().filter(|d| d.health == DOWN).count(),
        })
    }

    /// Remove a device and its rate history.
    pub fn unregister(&self, name: &str) -> bool {
        let mut state = self.lock_state();
        if state.devices.remove(name).is_none() {
            return false;
        }
        state.call_timestamps.remove(name);
        true
    }

    fn lock_state(&self) -> MutexGuard<'_, DeviceState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

fn summary(device: &DeviceRecord) -> Value {
    json!({
        "name": device.name,
        "type": device.device_type,
        "health": device.health,
        "rate_limit": device.rate_limit,
        "calls": device.call_count,
        "errors": device.error_count,
        "last_used": device.last_used,
        "description": device.description,
    })
}

fn round(value: f64, precision: u32) -> f64 {
    let factor = 10_f64.powi(precision as i32);
    (value * factor).round() / factor
}
