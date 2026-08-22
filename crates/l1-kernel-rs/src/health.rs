//! Provider-neutral health-result aggregation candidate for the L1 kernel.
//!
//! Module imports, clocks, singleton probes, and runtime subsystem providers
//! remain Python-owned. This module only aggregates explicit check results.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// Decimal places retained for elapsed health-check time.
pub const HEALTHCHECK_ELAPSED_PRECISION: u32 = 2;

/// One explicit subsystem result supplied by a health-check adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HealthCheck {
    /// Status label emitted by the provider (`OK`, `DEGRADED`, or `FAILED`).
    pub status: String,
    /// Bounded human-readable detail owned by the provider.
    pub detail: String,
}

/// Aggregated health result with the Python wire shape.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HealthSummary {
    /// Overall status, with `DOWN` taking precedence over `DEGRADED`.
    pub status: String,
    /// Number of explicit subsystem results.
    pub module_count: usize,
    /// Results whose status is exactly `OK`.
    pub healthy: usize,
    /// Results that are neither `OK` nor `FAILED`.
    pub degraded: usize,
    /// Results whose status is exactly `FAILED`.
    pub failed: usize,
    /// Explicit subsystem results, retained for inspection.
    pub subsystems: BTreeMap<String, HealthCheck>,
    /// Caller-supplied elapsed time rounded to the contract precision.
    pub elapsed_ms: f64,
}

/// Aggregate explicit health results without probing runtime state.
pub fn aggregate_health(
    subsystems: &BTreeMap<String, HealthCheck>,
    elapsed_ms: f64,
) -> HealthSummary {
    let healthy = subsystems
        .values()
        .filter(|result| result.status == "OK")
        .count();
    let failed = subsystems
        .values()
        .filter(|result| result.status == "FAILED")
        .count();
    let degraded = subsystems.len().saturating_sub(healthy + failed);
    let status = if failed > 0 {
        "DOWN"
    } else if degraded > 0 {
        "DEGRADED"
    } else {
        "OK"
    };

    HealthSummary {
        status: status.to_owned(),
        module_count: subsystems.len(),
        healthy,
        degraded,
        failed,
        subsystems: subsystems.clone(),
        elapsed_ms: round_half_even(elapsed_ms, HEALTHCHECK_ELAPSED_PRECISION),
    }
}

fn round_half_even(value: f64, precision: u32) -> f64 {
    let factor = 10_f64.powi(precision as i32);
    let sign = if value.is_sign_negative() { -1.0 } else { 1.0 };
    let scaled = value.abs() * factor;
    let lower = scaled.floor();
    let fraction = scaled - lower;
    let rounded = if fraction < 0.5 {
        lower
    } else if fraction > 0.5 {
        lower + 1.0
    } else if (lower as u64).is_multiple_of(2) {
        lower
    } else {
        lower + 1.0
    };
    sign * rounded / factor
}
