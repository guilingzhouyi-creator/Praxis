//! Provider-neutral lifecycle state machine and checkpoint record candidate.

use std::sync::{Arc, Mutex, MutexGuard, OnceLock, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

/// Version of the serialized lifecycle record contract.
pub const LIFECYCLE_RECORD_VERSION: u32 = 1;

/// System lifecycle states mirrored from `l1.kernel.lifecycle`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LifecycleState {
    /// No system components are active.
    Halted,
    /// Installation work is in progress.
    Installing,
    /// Boot work is in progress.
    Booting,
    /// The system is serving requests.
    Active,
    /// Shutdown is draining active work.
    Draining,
    /// A boot or runtime failure was recorded.
    Crashed,
}

impl LifecycleState {
    /// Return the stable Python-compatible state spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Halted => "halted",
            Self::Installing => "installing",
            Self::Booting => "booting",
            Self::Active => "active",
            Self::Draining => "draining",
            Self::Crashed => "crashed",
        }
    }

    /// Parse a persisted state without accepting unknown values.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "halted" => Some(Self::Halted),
            "installing" => Some(Self::Installing),
            "booting" => Some(Self::Booting),
            "active" => Some(Self::Active),
            "draining" => Some(Self::Draining),
            "crashed" => Some(Self::Crashed),
            _ => None,
        }
    }

    fn can_transition_to(self, target: Self) -> bool {
        matches!(
            (self, target),
            (Self::Halted, Self::Installing | Self::Booting)
                | (Self::Installing, Self::Booting | Self::Crashed)
                | (Self::Booting, Self::Active | Self::Crashed)
                | (Self::Active, Self::Draining | Self::Crashed)
                | (Self::Draining, Self::Halted | Self::Crashed)
                | (Self::Crashed, Self::Booting)
        )
    }
}

/// Durable lifecycle fields crossing the checkpoint adapter boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct LifecycleRecord {
    /// Installation counter or release marker.
    pub install_version: u64,
    /// Schema version used by the persisted state.
    pub schema_version: String,
    /// Application/kernel version at the last install or upgrade.
    pub app_version: String,
    /// Timestamp of the last boot attempt.
    pub last_boot: String,
    /// Whether the last boot completed successfully.
    pub last_boot_success: bool,
    /// Timestamp of the last shutdown attempt.
    pub last_shutdown: String,
    /// Whether the last shutdown was clean.
    pub last_shutdown_clean: bool,
    /// Number of successful boot attempts recorded.
    pub boot_count: u64,
    /// Serialized current lifecycle state.
    pub lifecycle_state: String,
}

impl Default for LifecycleRecord {
    fn default() -> Self {
        Self {
            install_version: 0,
            schema_version: String::new(),
            app_version: String::new(),
            last_boot: String::new(),
            last_boot_success: false,
            last_shutdown: String::new(),
            last_shutdown_clean: false,
            boot_count: 0,
            lifecycle_state: LifecycleState::Halted.as_str().to_owned(),
        }
    }
}

/// Structured failures for lifecycle restore and serialization.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LifecycleErrorCode {
    /// Persisted state contains an unknown lifecycle state.
    InvalidState,
    /// A JSON checkpoint could not be decoded or encoded.
    InvalidRecord,
}

/// Lifecycle error that remains independent of filesystem providers.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LifecycleError {
    /// Stable machine-readable category.
    pub code: LifecycleErrorCode,
    /// Human-readable context for the adapter or audit layer.
    pub message: String,
}

impl LifecycleError {
    fn new(code: LifecycleErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

/// Thread-safe lifecycle state machine with explicit snapshot/restore seams.
pub struct LifecycleRegistry {
    state: Mutex<LifecycleInner>,
}

#[derive(Debug)]
struct LifecycleInner {
    state: LifecycleState,
    record: LifecycleRecord,
}

impl LifecycleRegistry {
    /// Create a halted registry with an empty record.
    pub fn new() -> Self {
        Self {
            state: Mutex::new(LifecycleInner {
                state: LifecycleState::Halted,
                record: LifecycleRecord::default(),
            }),
        }
    }

    /// Create a registry by restoring a record, rejecting unknown states.
    pub fn from_record(record: LifecycleRecord) -> Result<Self, LifecycleError> {
        let state = LifecycleState::parse(&record.lifecycle_state).ok_or_else(|| {
            LifecycleError::new(
                LifecycleErrorCode::InvalidState,
                format!("unknown lifecycle state '{}'", record.lifecycle_state),
            )
        })?;
        Ok(Self {
            state: Mutex::new(LifecycleInner { state, record }),
        })
    }

    /// Return the current state.
    pub fn state(&self) -> LifecycleState {
        self.lock_state().state
    }

    /// Return an immutable clone of the current durable record.
    pub fn snapshot(&self) -> LifecycleRecord {
        self.lock_state().record.clone()
    }

    /// Restore a record atomically after validating its state value.
    pub fn restore(&self, record: LifecycleRecord) -> Result<(), LifecycleError> {
        let state = LifecycleState::parse(&record.lifecycle_state).ok_or_else(|| {
            LifecycleError::new(
                LifecycleErrorCode::InvalidState,
                format!("unknown lifecycle state '{}'", record.lifecycle_state),
            )
        })?;
        let mut inner = self.lock_state();
        inner.state = state;
        inner.record = record;
        Ok(())
    }

    /// Encode the current record for a provider-owned checkpoint.
    pub fn encode(&self) -> Result<Vec<u8>, LifecycleError> {
        serde_json::to_vec(&self.snapshot()).map_err(|error| {
            LifecycleError::new(
                LifecycleErrorCode::InvalidRecord,
                format!("encode lifecycle record failed: {error}"),
            )
        })
    }

    /// Decode and restore a provider-supplied checkpoint.
    pub fn restore_encoded(&self, bytes: &[u8]) -> Result<(), LifecycleError> {
        let record: LifecycleRecord = serde_json::from_slice(bytes).map_err(|error| {
            LifecycleError::new(
                LifecycleErrorCode::InvalidRecord,
                format!("decode lifecycle record failed: {error}"),
            )
        })?;
        self.restore(record)
    }

    /// Validate and apply one state transition; return false when disallowed.
    pub fn transition(&self, target: LifecycleState) -> bool {
        let mut inner = self.lock_state();
        if !inner.state.can_transition_to(target) {
            return false;
        }
        inner.state = target;
        inner.record.lifecycle_state = target.as_str().to_owned();
        true
    }

    /// Return whether a transition is valid without mutating state.
    pub fn can_transition(&self, target: LifecycleState) -> bool {
        self.lock_state().state.can_transition_to(target)
    }

    /// Return whether installation or recovery work is required.
    pub fn should_install(&self, current_schema: &str) -> bool {
        let record = self.lock_state().record.clone();
        if record.install_version == 0 {
            return true;
        }
        if record.schema_version != current_schema {
            return true;
        }
        if !record.last_shutdown.is_empty() {
            return !record.last_shutdown_clean;
        }
        record.boot_count > 0
    }

    /// Record a successful boot with a generated timestamp.
    pub fn record_boot_success(&self) {
        self.record_boot_success_at(unix_timestamp());
    }

    /// Record a successful boot with a deterministic timestamp for adapters/tests.
    pub fn record_boot_success_at(&self, timestamp: impl Into<String>) {
        let mut inner = self.lock_state();
        inner.record.boot_count = inner.record.boot_count.saturating_add(1);
        inner.record.last_boot = timestamp.into();
        inner.record.last_boot_success = true;
        inner.record.lifecycle_state = inner.state.as_str().to_owned();
    }

    /// Record a failed boot with a generated timestamp.
    pub fn record_boot_failure(&self) {
        self.record_boot_failure_at(unix_timestamp());
    }

    /// Record a failed boot with a deterministic timestamp for adapters/tests.
    pub fn record_boot_failure_at(&self, timestamp: impl Into<String>) {
        let mut inner = self.lock_state();
        inner.record.last_boot = timestamp.into();
        inner.record.last_boot_success = false;
        inner.record.lifecycle_state = inner.state.as_str().to_owned();
    }

    /// Record a clean or unclean shutdown with a generated timestamp.
    pub fn record_shutdown(&self, clean: bool) {
        self.record_shutdown_at(clean, unix_timestamp());
    }

    /// Record a clean or unclean shutdown with a deterministic timestamp.
    pub fn record_shutdown_at(&self, clean: bool, timestamp: impl Into<String>) {
        let mut inner = self.lock_state();
        inner.record.last_shutdown = timestamp.into();
        inner.record.last_shutdown_clean = clean;
        inner.record.lifecycle_state = inner.state.as_str().to_owned();
    }

    fn lock_state(&self) -> MutexGuard<'_, LifecycleInner> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for LifecycleRegistry {
    fn default() -> Self {
        Self::new()
    }
}

static GLOBAL_LIFECYCLE: OnceLock<Mutex<Option<Arc<LifecycleRegistry>>>> = OnceLock::new();

fn global_lifecycle() -> &'static Mutex<Option<Arc<LifecycleRegistry>>> {
    GLOBAL_LIFECYCLE.get_or_init(|| Mutex::new(None))
}

/// Return the process-wide lifecycle candidate.
pub fn get_lifecycle() -> Arc<LifecycleRegistry> {
    let mut slot = global_lifecycle()
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    Arc::clone(slot.get_or_insert_with(|| Arc::new(LifecycleRegistry::new())))
}

/// Reset the process-wide lifecycle candidate for test isolation.
pub fn reset_lifecycle() {
    *global_lifecycle()
        .lock()
        .unwrap_or_else(PoisonError::into_inner) = None;
}

/// Return the process-wide lifecycle state.
pub fn state() -> LifecycleState {
    get_lifecycle().state()
}

/// Apply a transition on the process-wide lifecycle candidate.
pub fn transition(target: LifecycleState) -> bool {
    get_lifecycle().transition(target)
}

fn unix_timestamp() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64());
    format!("{seconds:.6}")
}
