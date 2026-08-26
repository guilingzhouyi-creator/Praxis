//! Aggregate-only input activity probe for the Rust/TS boundary.
//!
//! The probe consumes host-injected observations and never opens device nodes,
//! parses key values, stores pointer coordinates, or reads a system clock. A
//! platform adapter owns those effects and supplies only the bounded values
//! defined here.

use std::collections::BTreeSet;
use std::fmt::{Display, Formatter};

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
    fn as_wire(self) -> &'static str {
        match self {
            Self::Granted => "granted",
            Self::Denied => "denied",
            Self::Unavailable => "unavailable",
        }
    }
}

/// One host-injected aggregate observation with no raw input content.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputActivityObservation {
    /// Stable adapter/source label, never a device path.
    pub source: String,
    /// Permission state for this source.
    pub permission: InputActivityPermission,
    /// Whether keyboard activity is currently asserted by the adapter.
    pub keyboard_active: bool,
    /// Whether pointer activity is currently asserted by the adapter.
    pub pointer_active: bool,
    /// Caller-supplied timestamp of the latest aggregate activity.
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
    pub idle_after_seconds: f64,
    /// Maximum number of source observations accepted per aggregation.
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

impl InputActivityProbe {
    /// Construct a probe with validated explicit bounds.
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
