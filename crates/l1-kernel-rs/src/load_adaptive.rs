//! Provider-neutral load-adaptive worker-pool control law candidate.

use serde::{Deserialize, Serialize};

/// EWMA smoothing factor mirrored from Python `params.api`.
pub const LOAD_ADAPTIVE_EWMA_ALPHA: f64 = 0.3;
/// Queue ratio below which the controller shrinks.
pub const LOAD_ADAPTIVE_LOW_RATIO: f64 = 0.2;
/// Queue ratio above which the controller grows.
pub const LOAD_ADAPTIVE_HIGH_RATIO: f64 = 0.6;
/// Consecutive out-of-band samples required before a decision.
pub const LOAD_ADAPTIVE_HYSTERESIS_SAMPLES: u32 = 3;
/// Cooldown duration after a growth or shrink decision.
pub const LOAD_ADAPTIVE_COOLDOWN_S: f64 = 5.0;
/// Number of workers added by a normal growth decision.
pub const LOAD_ADAPTIVE_GROW_STEP: u64 = 2;
/// Worker-count divisor used by a shrink decision.
pub const LOAD_ADAPTIVE_SHRINK_FACTOR: u64 = 2;
/// Fraction of the task timeout used to identify slow tasks.
pub const LOAD_ADAPTIVE_SLOW_TASK_RATIO: f64 = 0.5;
/// Default task timeout used by the slow-task threshold.
pub const WORKER_POOL_TASK_TIMEOUT: f64 = 30.0;

/// Control action emitted by the load-adaptive controller.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Action {
    /// Keep the current worker count.
    #[default]
    Hold,
    /// Add the configured growth step.
    Grow,
    /// Reduce the worker count by the configured divisor.
    Shrink,
    /// Add twice the normal growth step for slow tasks.
    GrowFast,
}

/// Load signals consumed by one control-law cycle.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ControllerMetrics {
    /// Current queued work divided by queue capacity.
    pub queue_ratio: f64,
    /// Completed work rate, reserved for future control policies.
    pub completion_rate: f64,
    /// Active worker ratio, reserved for future control policies.
    pub active_ratio: f64,
    /// Elapsed time of the sampled task in seconds.
    pub task_elapsed: f64,
    /// Current resident worker count.
    pub worker_count: u64,
    /// Minimum resident worker count.
    pub worker_min: u64,
    /// Maximum resident worker count.
    pub worker_max: u64,
}

impl Default for ControllerMetrics {
    fn default() -> Self {
        Self {
            queue_ratio: 0.0,
            completion_rate: 0.0,
            active_ratio: 0.0,
            task_elapsed: 0.0,
            worker_count: 0,
            worker_min: 1,
            worker_max: 32,
        }
    }
}

/// Configuration values for one controller instance.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ControllerConfig {
    /// Lower target-band boundary.
    pub low_ratio: f64,
    /// Upper target-band boundary.
    pub high_ratio: f64,
    /// EWMA smoothing factor.
    pub ewma_alpha: f64,
    /// Number of consecutive out-of-band samples required.
    pub hysteresis_samples: u32,
    /// Cooldown duration in seconds.
    pub cooldown_s: f64,
    /// Normal worker growth step.
    pub grow_step: u64,
    /// Worker shrink divisor.
    pub shrink_factor: u64,
    /// Slow-task threshold as a fraction of the task timeout.
    pub slow_task_ratio: f64,
    /// Task timeout in seconds.
    pub task_timeout: f64,
}

impl Default for ControllerConfig {
    fn default() -> Self {
        Self {
            low_ratio: LOAD_ADAPTIVE_LOW_RATIO,
            high_ratio: LOAD_ADAPTIVE_HIGH_RATIO,
            ewma_alpha: LOAD_ADAPTIVE_EWMA_ALPHA,
            hysteresis_samples: LOAD_ADAPTIVE_HYSTERESIS_SAMPLES,
            cooldown_s: LOAD_ADAPTIVE_COOLDOWN_S,
            grow_step: LOAD_ADAPTIVE_GROW_STEP,
            shrink_factor: LOAD_ADAPTIVE_SHRINK_FACTOR,
            slow_task_ratio: LOAD_ADAPTIVE_SLOW_TASK_RATIO,
            task_timeout: WORKER_POOL_TASK_TIMEOUT,
        }
    }
}

/// Structured configuration errors at the candidate boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ControllerError {
    /// The target-band boundaries are invalid.
    InvalidRatios,
    /// The EWMA factor is outside the open/closed interval `(0, 1]`.
    InvalidAlpha,
    /// A zero shrink divisor would make a shrink decision undefined.
    InvalidShrinkFactor,
}

/// One decision returned by a control-law cycle.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Decision {
    /// Chosen control action.
    pub action: Action,
    /// Worker target after the action.
    pub target_workers: u64,
    /// Smoothed queue ratio.
    pub ewma_depth: f64,
    /// Whether the cycle was suppressed by cooldown.
    pub in_cooldown: bool,
    /// Stable human-readable reason retained for observability.
    pub reason: String,
}

/// Serializable controller state for inspection without exposing internals.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StateSnapshot {
    /// Smoothed queue ratio rounded to four decimal places.
    pub ewma: f64,
    /// Consecutive out-of-band sample count.
    pub out_of_bounds_count: u32,
    /// Elapsed time since the last decision, supplied by the caller.
    pub last_decision_elapsed: f64,
    /// Number of decisions emitted so far.
    pub decisions_total: u64,
    /// Effective lower target-band boundary.
    pub low_ratio: f64,
    /// Effective upper target-band boundary.
    pub high_ratio: f64,
    /// Effective EWMA factor.
    pub ewma_alpha: f64,
    /// Effective hysteresis sample count.
    pub hysteresis_samples: u32,
    /// Effective cooldown duration.
    pub cooldown_s: f64,
    /// Effective growth step.
    pub grow_step: u64,
    /// Effective shrink divisor.
    pub shrink_factor: u64,
}

#[derive(Debug, Clone, Copy, Default)]
struct ControllerState {
    ewma: f64,
    out_of_bounds_count: u32,
    last_decision_at: f64,
    decisions_total: u64,
}

/// Pure load-adaptive worker-pool control law.
pub struct LoadAdaptiveController {
    config: ControllerConfig,
    state: ControllerState,
}

impl LoadAdaptiveController {
    /// Create a controller after validating its target band and smoothing factor.
    pub fn new(config: ControllerConfig) -> Result<Self, ControllerError> {
        if config.low_ratio < 0.0
            || config.low_ratio >= config.high_ratio
            || config.high_ratio > 1.0
        {
            return Err(ControllerError::InvalidRatios);
        }
        if !(0.0 < config.ewma_alpha && config.ewma_alpha <= 1.0) {
            return Err(ControllerError::InvalidAlpha);
        }
        if config.shrink_factor == 0 {
            return Err(ControllerError::InvalidShrinkFactor);
        }
        Ok(Self {
            config,
            state: ControllerState::default(),
        })
    }

    /// Create a controller with the Python parameter defaults.
    pub fn with_defaults() -> Self {
        Self::new(ControllerConfig::default()).expect("default controller config is valid")
    }

    /// Run one control cycle using an explicit monotonic timestamp.
    pub fn decide(&mut self, metrics: ControllerMetrics, now: f64) -> Decision {
        let ewma = self.update_ewma(metrics.queue_ratio);
        let in_cooldown = now - self.state.last_decision_at < self.config.cooldown_s;
        if in_cooldown {
            return Decision {
                action: Action::Hold,
                target_workers: metrics.worker_count,
                ewma_depth: ewma,
                in_cooldown: true,
                reason: "in cooldown".to_owned(),
            };
        }

        let in_band = self.config.low_ratio <= ewma && ewma <= self.config.high_ratio;
        if in_band {
            self.state.out_of_bounds_count = 0;
            return Decision {
                action: Action::Hold,
                target_workers: metrics.worker_count,
                ewma_depth: ewma,
                in_cooldown: false,
                reason: "within target band".to_owned(),
            };
        }

        self.state.out_of_bounds_count = self.state.out_of_bounds_count.saturating_add(1);
        if self.state.out_of_bounds_count < self.config.hysteresis_samples {
            return Decision {
                action: Action::Hold,
                target_workers: metrics.worker_count,
                ewma_depth: ewma,
                in_cooldown: false,
                reason: format!(
                    "hysteresis ({}/{})",
                    self.state.out_of_bounds_count, self.config.hysteresis_samples
                ),
            };
        }

        let mut target = metrics.worker_count;
        let mut action = Action::Hold;
        let mut reason = String::new();
        if ewma > self.config.high_ratio {
            let is_slow = metrics.task_elapsed > self.slow_task_seconds()
                && metrics.queue_ratio > self.config.high_ratio;
            let step = if is_slow {
                action = Action::GrowFast;
                self.config.grow_step.saturating_mul(2)
            } else {
                action = Action::Grow;
                self.config.grow_step
            };
            target = metrics
                .worker_count
                .saturating_add(step)
                .min(metrics.worker_max);
            reason = if is_slow {
                format!("slow tasks detected, grow fast +{step}")
            } else {
                format!(
                    "queue ratio {:.3} > {}, grow +{}",
                    ewma, self.config.high_ratio, step
                )
            };
        } else if ewma < self.config.low_ratio {
            target = (metrics.worker_count / self.config.shrink_factor).max(metrics.worker_min);
            action = Action::Shrink;
            reason = format!(
                "queue ratio {:.3} < {}, shrink to {}",
                ewma, self.config.low_ratio, target
            );
        }

        self.state.last_decision_at = now;
        self.state.out_of_bounds_count = 0;
        self.state.decisions_total = self.state.decisions_total.saturating_add(1);
        Decision {
            action,
            target_workers: target,
            ewma_depth: ewma,
            in_cooldown: false,
            reason,
        }
    }

    /// Reset EWMA, hysteresis, cooldown, and decision counters.
    pub fn reset(&mut self) {
        self.state = ControllerState::default();
    }

    /// Return an observable state snapshot using a caller-provided clock.
    pub fn state(&self, now: f64) -> StateSnapshot {
        StateSnapshot {
            ewma: round(self.state.ewma, 4),
            out_of_bounds_count: self.state.out_of_bounds_count,
            last_decision_elapsed: if self.state.last_decision_at != 0.0 {
                round(now - self.state.last_decision_at, 2)
            } else {
                0.0
            },
            decisions_total: self.state.decisions_total,
            low_ratio: self.config.low_ratio,
            high_ratio: self.config.high_ratio,
            ewma_alpha: self.config.ewma_alpha,
            hysteresis_samples: self.config.hysteresis_samples,
            cooldown_s: self.config.cooldown_s,
            grow_step: self.config.grow_step,
            shrink_factor: self.config.shrink_factor,
        }
    }

    /// Return the effective configuration.
    pub const fn config(&self) -> ControllerConfig {
        self.config
    }

    fn slow_task_seconds(&self) -> f64 {
        self.config.task_timeout * self.config.slow_task_ratio
    }

    fn update_ewma(&mut self, queue_ratio: f64) -> f64 {
        if self.state.decisions_total == 0 && self.state.ewma == 0.0 {
            self.state.ewma = queue_ratio;
        } else {
            self.state.ewma = self.config.ewma_alpha * queue_ratio
                + (1.0 - self.config.ewma_alpha) * self.state.ewma;
        }
        self.state.ewma
    }
}

impl Default for LoadAdaptiveController {
    fn default() -> Self {
        Self::with_defaults()
    }
}

fn round(value: f64, places: i32) -> f64 {
    let factor = 10_f64.powi(places);
    (value * factor).round() / factor
}
