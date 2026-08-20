//! Provider-neutral memory-ring swap planning candidate for the L1 kernel.
//!
//! MemoryService I/O, allocator pressure sampling, clocks, worker threads,
//! and persistence remain Python-owned. This module only plans ring actions
//! from explicit entry and pressure snapshots.

use serde::{Deserialize, Serialize};

/// Importance below which a working entry moves directly to ring 3.
pub const SWAPPER_SWAP_OUT_IMPORTANCE: f64 = 0.3;
/// Importance below which an expired short entry moves to ring 3.
pub const SWAPPER_COMPACT_IMPORTANCE: f64 = 0.5;
/// Pressure percentage required before a ring action is planned.
pub const SWAPPER_PRESSURE_HIGH: f64 = 90.0;
/// Default number of working entries considered per pass.
pub const SWAPPER_SWAP_COUNT: usize = 10;

/// Explicit memory entry facts used by the planner.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SwapEntry {
    /// Stable memory-entry identifier.
    pub id: String,
    /// Entry importance used for ring placement.
    pub importance: f64,
    /// Remaining TTL in seconds, or zero for no expiry.
    pub ttl: f64,
    /// Expiration result already evaluated by the provider.
    pub expired: bool,
}

/// One planned move between memory rings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SwapAction {
    /// Entry identifier to move.
    pub id: String,
    /// Destination ring number.
    pub target_ring: u8,
}

/// Explicit pressure values supplied by the allocator and memory adapter.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PressureSnapshot {
    /// Whether allocator pressure crossed the low-pressure threshold.
    pub under_pressure: bool,
    /// Working-ring occupancy percentage.
    pub working_pct: f64,
    /// Short-ring occupancy percentage.
    pub short_pct: f64,
    /// Long-ring occupancy percentage.
    pub long_pct: f64,
}

/// Planned pressure responses before any MemoryService mutation occurs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PressurePlan {
    /// Whether working entries should be moved out.
    pub swap_out_working: bool,
    /// Whether expired short entries should be compacted.
    pub compact_short_term: bool,
    /// Whether long-term memory is full enough to report.
    pub long_term_full: bool,
}

/// Plan working-ring destinations while preserving provider order.
pub fn plan_swap_out(
    entries: &[SwapEntry],
    count: usize,
    importance_threshold: f64,
) -> Vec<SwapAction> {
    entries
        .iter()
        .take(count)
        .map(|entry| SwapAction {
            id: entry.id.clone(),
            target_ring: if entry.importance < importance_threshold {
                3
            } else {
                2
            },
        })
        .collect()
}

/// Plan short-ring compaction for expired, low-importance entries.
pub fn plan_compaction(entries: &[SwapEntry], importance_threshold: f64) -> Vec<SwapAction> {
    entries
        .iter()
        .filter(|entry| entry.importance < importance_threshold && entry.ttl > 0.0 && entry.expired)
        .map(|entry| SwapAction {
            id: entry.id.clone(),
            target_ring: 3,
        })
        .collect()
}

/// Plan pressure responses from explicit occupancy percentages.
pub fn plan_pressure(snapshot: PressureSnapshot, high_threshold: f64) -> PressurePlan {
    if !snapshot.under_pressure {
        return PressurePlan {
            swap_out_working: false,
            compact_short_term: false,
            long_term_full: false,
        };
    }
    PressurePlan {
        swap_out_working: snapshot.working_pct >= high_threshold,
        compact_short_term: snapshot.short_pct >= high_threshold,
        long_term_full: snapshot.long_pct >= high_threshold,
    }
}

#[cfg(test)]
mod tests {
    use super::{PressureSnapshot, SwapEntry, plan_compaction, plan_pressure, plan_swap_out};
    use serde::Deserialize;
    use serde_json::Value;

    #[derive(Debug, Deserialize)]
    struct SwapperVectors {
        cases: Vec<SwapperCase>,
        pressure: Vec<PressureCase>,
    }

    #[derive(Debug, Deserialize)]
    struct SwapperCase {
        entries: Vec<SwapEntry>,
        count: Option<usize>,
        expected_swap_out: Value,
        expected_compaction: Value,
    }

    #[derive(Debug, Deserialize)]
    struct PressureCase {
        snapshot: PressureSnapshot,
        high_threshold: f64,
        expected: Value,
    }

    #[test]
    fn shared_swapper_vectors_match_candidate() {
        let raw = include_str!("../../../tests/fixtures/kernel_swapper_vectors.json");
        let vectors: SwapperVectors = serde_json::from_str(raw).expect("valid swapper vectors");
        for case in vectors.cases {
            let count = case.count.unwrap_or(super::SWAPPER_SWAP_COUNT);
            let actual_swap = serde_json::to_value(plan_swap_out(
                &case.entries,
                count,
                super::SWAPPER_SWAP_OUT_IMPORTANCE,
            ))
            .expect("serializable swap plan");
            let actual_compaction = serde_json::to_value(plan_compaction(
                &case.entries,
                super::SWAPPER_COMPACT_IMPORTANCE,
            ))
            .expect("serializable compaction plan");
            assert_eq!(actual_swap, case.expected_swap_out);
            assert_eq!(actual_compaction, case.expected_compaction);
        }
        for case in vectors.pressure {
            let actual = serde_json::to_value(plan_pressure(case.snapshot, case.high_threshold))
                .expect("serializable pressure plan");
            assert_eq!(actual, case.expected);
        }
    }

    #[test]
    fn pressure_plan_fails_closed_when_not_under_pressure() {
        let plan = plan_pressure(
            PressureSnapshot {
                under_pressure: false,
                working_pct: 100.0,
                short_pct: 100.0,
                long_pct: 100.0,
            },
            90.0,
        );
        assert!(!plan.swap_out_working);
        assert!(!plan.compact_short_term);
        assert!(!plan.long_term_full);
    }
}
