//! Aggregate-only input activity probe for the Rust/TS boundary.
//!
//! The probe consumes host-injected observations and never opens device nodes,
//! parses key values, stores pointer coordinates, or reads a system clock. A
//! platform adapter owns those effects and supplies only the bounded values
//! defined here.

use std::collections::BTreeSet;
use std::fmt::{Display, Formatter};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::{Arc, Mutex, PoisonError};

use serde::{Deserialize, Serialize};

use crate::ports::{InputActivitySnapshot, InputActivityState};

/// Version of the aggregate input-activity value contract.
pub const INPUT_ACTIVITY_CONTRACT_VERSION: u32 = 1;
/// Default period after which an observed source becomes idle.
pub const DEFAULT_IDLE_AFTER_SECONDS: f64 = 5.0;
/// Maximum number of host sources accepted by the default probe.
pub const DEFAULT_MAX_SOURCES: usize = 16;

/// Permission result supplied by a host input adapter.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum InputActivityPermission {
    /// The adapter was allowed to observe aggregate activity.
    Granted,
    /// The adapter found a source but the host denied access.
    Denied,
    /// The host has no usable adapter or source.
    Unavailable,
}

impl InputActivityPermission {
    /// Return the stable permission spelling used by the port snapshot.
    pub const fn as_wire(self) -> &'static str {
        match self {
            Self::Granted => "granted",
            Self::Denied => "denied",
            Self::Unavailable => "unavailable",
        }
    }
}

/// One sample supplied by a host keyboard/pointer adapter.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputActivityHostSample {
    /// Caller-supplied current time for idle reduction.
    pub now: f64,
    /// Aggregate observations with no raw key or pointer content.
    pub observations: Vec<InputActivityObservation>,
}

/// Host-owned lifecycle and sampling seam for keyboard/pointer activity.
pub trait InputActivityHostAdapter: Send + Sync {
    /// Start host observation and report permission or availability.
    fn start(&self) -> InputActivityPermission;
    /// Stop observation and release host-owned resources.
    fn stop(&self);
    /// Return one aggregate sample using a host-supplied timestamp.
    fn sample(&self) -> Result<InputActivityHostSample, InputActivityPermission>;
}

/// One host-injected aggregate observation with no raw input content.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputActivityObservation {
    /// Stable adapter/source label, never a device path.
    /// Provenance label of the aggregate snapshot.
    pub source: String,
    /// Permission state for this source.
    /// Granted permission state (aggregate-only contract).
    pub permission: InputActivityPermission,
    /// Whether keyboard activity is currently asserted by the adapter.
    /// Keyboard activity within the idle window.
    pub keyboard_active: bool,
    /// Whether pointer activity is currently asserted by the adapter.
    /// Pointer activity within the idle window.
    pub pointer_active: bool,
    /// Caller-supplied timestamp of the latest aggregate activity.
    /// Last activity timestamp (Unix seconds).
    pub last_activity_at: f64,
}

impl InputActivityObservation {
    /// Build an aggregate observation from host-supplied values.
    pub fn new(
        source: impl Into<String>,
        permission: InputActivityPermission,
        keyboard_active: bool,
        pointer_active: bool,
        last_activity_at: f64,
    ) -> Self {
        Self {
            source: source.into(),
            permission,
            keyboard_active,
            pointer_active,
            last_activity_at,
        }
    }
}

/// Explicit bounds for host input aggregation.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct InputActivityProbeConfig {
    /// Idle threshold applied to the caller-supplied timestamps.
    /// Idle threshold applied to activity flags.
    pub idle_after_seconds: f64,
    /// Maximum number of source observations accepted per aggregation.
    /// Maximum distinct sources per aggregation batch.
    pub max_sources: usize,
}

impl Default for InputActivityProbeConfig {
    fn default() -> Self {
        Self {
            idle_after_seconds: DEFAULT_IDLE_AFTER_SECONDS,
            max_sources: DEFAULT_MAX_SOURCES,
        }
    }
}

impl InputActivityProbeConfig {
    /// Validate explicit aggregation bounds.
    ///
    /// # Errors
    ///
    /// InvalidConfig for non-positive idle window or source cap.
    pub fn validate(self) -> Result<Self, InputActivityProbeError> {
        if !self.idle_after_seconds.is_finite() || self.idle_after_seconds <= 0.0 {
            return Err(InputActivityProbeError::InvalidConfig(
                "idle_after_seconds must be finite and positive".to_owned(),
            ));
        }
        if self.max_sources == 0 {
            return Err(InputActivityProbeError::InvalidConfig(
                "max_sources must be positive".to_owned(),
            ));
        }
        Ok(self)
    }
}

/// Fail-closed errors from aggregate input observation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum InputActivityProbeError {
    /// The explicit bounds are invalid.
    InvalidConfig(String),
    /// A source observation violates the value contract.
    InvalidObservation { source: String, reason: String },
    /// More source observations were supplied than the configured bound.
    TooManySources { max_sources: usize },
    /// The caller-supplied current time is invalid.
    InvalidNow,
}

impl Display for InputActivityProbeError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidConfig(reason) => {
                write!(formatter, "invalid input activity config: {reason}")
            }
            Self::InvalidObservation { source, reason } => {
                write!(
                    formatter,
                    "invalid input activity observation {source}: {reason}"
                )
            }
            Self::TooManySources { max_sources } => {
                write!(
                    formatter,
                    "input activity source limit exceeded: {max_sources}"
                )
            }
            Self::InvalidNow => {
                formatter.write_str("input activity now must be finite and non-negative")
            }
        }
    }
}

impl std::error::Error for InputActivityProbeError {}

/// Deterministic aggregate-only input activity probe.
#[derive(Debug, Clone, Copy)]
pub struct InputActivityProbe {
    config: InputActivityProbeConfig,
}

struct HostInputActivityState {
    running: bool,
    permission: InputActivityPermission,
    snapshot: InputActivitySnapshot,
}

/// Lifecycle port that reduces samples from a caller-owned host adapter.
///
/// Lifecycle calls are serialized so a concurrent permission transition cannot
/// overwrite a newer snapshot or leave the adapter running after `stop`.
pub struct HostInputActivityPort {
    probe: InputActivityProbe,
    adapter: Arc<dyn InputActivityHostAdapter>,
    state: Mutex<HostInputActivityState>,
    operation: Mutex<()>,
}

/// Composite host adapter for independently owned keyboard/pointer sources.
///
/// The composite owns only lifecycle coordination. Each source remains
/// responsible for platform permissions and aggregate-only sampling; no device
/// nodes, raw key values, or pointer coordinates cross this boundary.
pub struct CompositeInputActivityAdapter {
    sources: Vec<Arc<dyn InputActivityHostAdapter>>,
    permissions: Mutex<Vec<InputActivityPermission>>,
    operation: Mutex<()>,
}

impl CompositeInputActivityAdapter {
    /// Construct a composite from one or more host-owned input sources.
    ///
    /// # Errors
    ///
    /// InvalidConfig when no source is supplied. A source that is denied or
    /// unavailable at runtime is retained as a degraded member rather than
    /// preventing a separately granted source from being sampled.
    pub fn new(
        sources: Vec<Arc<dyn InputActivityHostAdapter>>,
    ) -> Result<Self, InputActivityProbeError> {
        if sources.is_empty() {
            return Err(InputActivityProbeError::InvalidConfig(
                "composite input adapter requires at least one source".to_owned(),
            ));
        }
        let source_count = sources.len();
        Ok(Self {
            sources,
            permissions: Mutex::new(vec![InputActivityPermission::Unavailable; source_count]),
            operation: Mutex::new(()),
        })
    }

    /// Return the number of independently managed host sources.
    pub fn source_count(&self) -> usize {
        self.sources.len()
    }

    fn aggregate_permission(permissions: &[InputActivityPermission]) -> InputActivityPermission {
        if permissions.contains(&InputActivityPermission::Granted) {
            InputActivityPermission::Granted
        } else if permissions.contains(&InputActivityPermission::Denied) {
            InputActivityPermission::Denied
        } else {
            InputActivityPermission::Unavailable
        }
    }

    fn stop_sources(&self) {
        for source in &self.sources {
            safe_stop(source.as_ref());
        }
    }
}

impl InputActivityHostAdapter for CompositeInputActivityAdapter {
    /// Start every source and retain any granted source for sampling.
    fn start(&self) -> InputActivityPermission {
        let _operation = self
            .operation
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let mut permissions = self
            .permissions
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let mut panicked = false;
        for (index, source) in self.sources.iter().enumerate() {
            permissions[index] = match catch_unwind(AssertUnwindSafe(|| source.start())) {
                Ok(permission) => permission,
                Err(_) => {
                    panicked = true;
                    InputActivityPermission::Unavailable
                }
            };
        }
        if panicked {
            self.stop_sources();
            permissions.fill(InputActivityPermission::Unavailable);
            return InputActivityPermission::Unavailable;
        }
        let permission = Self::aggregate_permission(&permissions);
        if permission != InputActivityPermission::Granted {
            self.stop_sources();
        }
        permission
    }

    /// Stop all sources and reset their permissions to unavailable.
    fn stop(&self) {
        let _operation = self
            .operation
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        self.stop_sources();
        let mut permissions = self
            .permissions
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        permissions.fill(InputActivityPermission::Unavailable);
    }

    /// Sample every currently granted source and merge aggregate observations.
    ///
    /// A denied or unavailable source is stopped and removed from subsequent
    /// samples while other granted sources continue. An invalid granted-source
    /// failure is returned unchanged so the outer port can fail closed.
    fn sample(&self) -> Result<InputActivityHostSample, InputActivityPermission> {
        let _operation = self
            .operation
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let mut permissions = self
            .permissions
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let mut now = 0.0_f64;
        let mut observations = Vec::new();
        let mut sampled = false;

        for (index, source) in self.sources.iter().enumerate() {
            if permissions[index] != InputActivityPermission::Granted {
                continue;
            }
            match catch_unwind(AssertUnwindSafe(|| source.sample())) {
                Err(_) => {
                    permissions[index] = InputActivityPermission::Unavailable;
                    return Err(InputActivityPermission::Granted);
                }
                Ok(Ok(sample)) => {
                    if !sample.now.is_finite() || sample.now < 0.0 {
                        permissions[index] = InputActivityPermission::Unavailable;
                        return Err(InputActivityPermission::Granted);
                    }
                    now = now.max(sample.now);
                    observations.extend(sample.observations);
                    sampled = true;
                }
                Ok(Err(
                    permission @ (InputActivityPermission::Denied
                    | InputActivityPermission::Unavailable),
                )) => {
                    safe_stop(source.as_ref());
                    permissions[index] = permission;
                }
                Ok(Err(InputActivityPermission::Granted)) => {
                    permissions[index] = InputActivityPermission::Unavailable;
                    return Err(InputActivityPermission::Granted);
                }
            }
        }

        if sampled {
            return Ok(InputActivityHostSample { now, observations });
        }
        Err(Self::aggregate_permission(&permissions))
    }
}

impl HostInputActivityPort {
    /// Construct a host port with explicit aggregation bounds and adapter.
    pub fn new(
        config: InputActivityProbeConfig,
        adapter: Arc<dyn InputActivityHostAdapter>,
    ) -> Result<Self, InputActivityProbeError> {
        let probe = InputActivityProbe::new(config)?;
        Ok(Self {
            probe,
            adapter,
            state: Mutex::new(HostInputActivityState {
                running: false,
                permission: InputActivityPermission::Unavailable,
                snapshot: unknown_snapshot(InputActivityPermission::Unavailable),
            }),
            operation: Mutex::new(()),
        })
    }

    /// Return the immutable reducer configuration.
    pub const fn config(&self) -> InputActivityProbeConfig {
        self.probe.config()
    }

    /// Start host observation; false means denied, unavailable, or panicked.
    pub fn start(&self) -> bool {
        let _operation = self
            .operation
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if self.lock_state().running {
            return true;
        }
        let permission = match catch_unwind(AssertUnwindSafe(|| self.adapter.start())) {
            Ok(permission) => permission,
            Err(_) => {
                safe_stop(self.adapter.as_ref());
                InputActivityPermission::Unavailable
            }
        };
        let mut state = self.lock_state();
        state.permission = permission;
        state.running = permission == InputActivityPermission::Granted;
        state.snapshot = unknown_snapshot(permission);
        state.running
    }

    /// Stop host observation and expose an unavailable snapshot.
    pub fn stop(&self) {
        let _operation = self
            .operation
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        safe_stop(self.adapter.as_ref());
        let mut state = self.lock_state();
        state.running = false;
        state.permission = InputActivityPermission::Unavailable;
        state.snapshot = unknown_snapshot(InputActivityPermission::Unavailable);
    }

    /// Reduce one host sample; permission loss or a panic stops observation.
    pub fn snapshot(&self) -> Result<InputActivitySnapshot, InputActivityProbeError> {
        let _operation = self
            .operation
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        if !self.lock_state().running {
            return Ok(self.lock_state().snapshot.clone());
        }
        let sample = match catch_unwind(AssertUnwindSafe(|| self.adapter.sample())) {
            Ok(Ok(sample)) => sample,
            Ok(Err(
                permission @ (InputActivityPermission::Denied
                | InputActivityPermission::Unavailable),
            )) => {
                safe_stop(self.adapter.as_ref());
                let mut state = self.lock_state();
                state.running = false;
                state.permission = permission;
                state.snapshot = unknown_snapshot(permission);
                return Ok(state.snapshot.clone());
            }
            Ok(Err(InputActivityPermission::Granted)) => {
                safe_stop(self.adapter.as_ref());
                let mut state = self.lock_state();
                state.running = false;
                state.permission = InputActivityPermission::Unavailable;
                state.snapshot = unknown_snapshot(InputActivityPermission::Unavailable);
                return Err(InputActivityProbeError::InvalidObservation {
                    source: "host-adapter".to_owned(),
                    reason: "sample failure cannot report granted permission".to_owned(),
                });
            }
            Err(_) => {
                safe_stop(self.adapter.as_ref());
                let mut state = self.lock_state();
                state.running = false;
                state.permission = InputActivityPermission::Unavailable;
                state.snapshot = unknown_snapshot(InputActivityPermission::Unavailable);
                return Err(InputActivityProbeError::InvalidObservation {
                    source: "host-adapter".to_owned(),
                    reason: "sample panicked".to_owned(),
                });
            }
        };
        match self.probe.aggregate(sample.now, sample.observations) {
            Ok(mut snapshot) => {
                snapshot.source = "host-adapter".to_owned();
                let mut state = self.lock_state();
                state.permission = InputActivityPermission::Granted;
                state.snapshot = snapshot.clone();
                Ok(snapshot)
            }
            Err(error) => {
                safe_stop(self.adapter.as_ref());
                let mut state = self.lock_state();
                state.running = false;
                state.permission = InputActivityPermission::Unavailable;
                state.snapshot = unknown_snapshot(InputActivityPermission::Unavailable);
                Err(error)
            }
        }
    }

    fn lock_state(&self) -> std::sync::MutexGuard<'_, HostInputActivityState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

fn safe_stop(adapter: &dyn InputActivityHostAdapter) {
    let _ = catch_unwind(AssertUnwindSafe(|| adapter.stop()));
}

fn unknown_snapshot(permission: InputActivityPermission) -> InputActivitySnapshot {
    InputActivitySnapshot {
        state: InputActivityState::Unknown,
        keyboard_active: false,
        pointer_active: false,
        last_activity_at: 0.0,
        idle_seconds: 0.0,
        source: "host-adapter".to_owned(),
        permission: permission.as_wire().to_owned(),
    }
}

impl InputActivityProbe {
    /// Construct a probe with validated explicit bounds.
    ///
    /// # Errors
    ///
    /// InvalidConfig forwarding [`InputActivityProbeConfig::validate`].
    pub fn new(config: InputActivityProbeConfig) -> Result<Self, InputActivityProbeError> {
        Ok(Self {
            config: config.validate()?,
        })
    }

    /// Return the immutable probe configuration.
    pub const fn config(&self) -> InputActivityProbeConfig {
        self.config
    }

    /// Aggregate bounded host observations at an injected current time.
    ///
    /// # Errors
    ///
    /// InvalidNow when the supplied clock regresses; TooManySources beyond
    /// `max_sources`; InvalidObservation for stale timestamps, unknown
    /// permissions, or privacy-contract violations (no raw input ever).
    pub fn aggregate<I>(
        &self,
        now: f64,
        observations: I,
    ) -> Result<InputActivitySnapshot, InputActivityProbeError>
    where
        I: IntoIterator<Item = InputActivityObservation>,
    {
        if !now.is_finite() || now < 0.0 {
            return Err(InputActivityProbeError::InvalidNow);
        }

        let mut seen_sources = BTreeSet::new();
        let mut count = 0usize;
        let mut granted = false;
        let mut denied = false;
        let mut keyboard_active = false;
        let mut pointer_active = false;
        let mut last_activity_at: f64 = 0.0;

        for observation in observations {
            count = count.saturating_add(1);
            if count > self.config.max_sources {
                return Err(InputActivityProbeError::TooManySources {
                    max_sources: self.config.max_sources,
                });
            }
            self.validate_observation(now, &observation)?;
            if !seen_sources.insert(observation.source.clone()) {
                return Err(InputActivityProbeError::InvalidObservation {
                    source: observation.source,
                    reason: "source identities must be unique".to_owned(),
                });
            }

            match observation.permission {
                InputActivityPermission::Granted => {
                    granted = true;
                    last_activity_at = last_activity_at.max(observation.last_activity_at);
                    let fresh =
                        now - observation.last_activity_at <= self.config.idle_after_seconds;
                    keyboard_active |= fresh && observation.keyboard_active;
                    pointer_active |= fresh && observation.pointer_active;
                }
                InputActivityPermission::Denied => denied = true,
                InputActivityPermission::Unavailable => {}
            }
        }

        let state = if keyboard_active || pointer_active {
            InputActivityState::Active
        } else if granted {
            InputActivityState::Idle
        } else {
            InputActivityState::Unknown
        };
        let permission = if granted {
            InputActivityPermission::Granted
        } else if denied {
            InputActivityPermission::Denied
        } else {
            InputActivityPermission::Unavailable
        };
        let idle_seconds = if last_activity_at > 0.0 {
            (now - last_activity_at).max(0.0)
        } else {
            0.0
        };

        Ok(InputActivitySnapshot {
            state,
            keyboard_active,
            pointer_active,
            last_activity_at,
            idle_seconds,
            source: "rust-probe".to_owned(),
            permission: permission.as_wire().to_owned(),
        })
    }

    fn validate_observation(
        &self,
        now: f64,
        observation: &InputActivityObservation,
    ) -> Result<(), InputActivityProbeError> {
        if observation.source.trim().is_empty()
            || observation.source.chars().any(char::is_whitespace)
        {
            return Err(InputActivityProbeError::InvalidObservation {
                source: observation.source.clone(),
                reason: "source must be a non-empty label without whitespace".to_owned(),
            });
        }
        if !observation.last_activity_at.is_finite()
            || observation.last_activity_at < 0.0
            || observation.last_activity_at > now
        {
            return Err(InputActivityProbeError::InvalidObservation {
                source: observation.source.clone(),
                reason: "last_activity_at must be finite, non-negative, and no later than now"
                    .to_owned(),
            });
        }
        if observation.permission != InputActivityPermission::Granted
            && (observation.keyboard_active || observation.pointer_active)
        {
            return Err(InputActivityProbeError::InvalidObservation {
                source: observation.source.clone(),
                reason: "activity flags require granted permission".to_owned(),
            });
        }
        if observation.permission == InputActivityPermission::Granted
            && (observation.keyboard_active || observation.pointer_active)
            && observation.last_activity_at == 0.0
        {
            return Err(InputActivityProbeError::InvalidObservation {
                source: observation.source.clone(),
                reason: "active observations require a positive activity timestamp".to_owned(),
            });
        }
        Ok(())
    }
}
