//! Independent memory-ring swap planning tests for the Rust kernel.

use l1_kernel_rs::swapper::{
    PressureSnapshot, SWAPPER_COMPACT_IMPORTANCE, SWAPPER_SWAP_COUNT, SWAPPER_SWAP_OUT_IMPORTANCE,
    SwapEntry, plan_compaction, plan_pressure, plan_swap_out,
};
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
    let raw = include_str!("../../../../tests/fixtures/kernel_swapper_vectors.json");
    let vectors: SwapperVectors = serde_json::from_str(raw).expect("valid swapper vectors");
    for case in vectors.cases {
        let count = case.count.unwrap_or(SWAPPER_SWAP_COUNT);
        let actual_swap = serde_json::to_value(plan_swap_out(
            &case.entries,
            count,
            SWAPPER_SWAP_OUT_IMPORTANCE,
        ))
        .expect("serializable swap plan");
        let actual_compaction =
            serde_json::to_value(plan_compaction(&case.entries, SWAPPER_COMPACT_IMPORTANCE))
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
