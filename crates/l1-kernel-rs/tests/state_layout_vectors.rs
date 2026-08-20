//! Cross-language vectors for the Rust-owned state layout boundary.

use l1_kernel_rs::state_layout::{
    StateAction, StateEntry, StateLayoutManifest, StateProbe, StateReason, decide_state_action,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct LayoutVectors {
    state_root: String,
    contract_version: u32,
    entries: Vec<StateEntry>,
    expected_entries: Vec<StateEntry>,
    probes: Vec<ProbeVector>,
}

#[derive(Debug, Deserialize)]
struct ProbeVector {
    probe: StateProbe,
    expected_action: StateAction,
    expected_reason: StateReason,
}

#[test]
fn shared_state_layout_vectors_match_rust_boundary() {
    let vectors: LayoutVectors = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_state_layout_vectors.json"
    ))
    .expect("valid state layout vectors");
    let manifest = StateLayoutManifest::new(
        vectors.state_root,
        vectors.contract_version,
        vectors.entries,
    )
    .expect("valid layout");
    assert_eq!(manifest.entries, vectors.expected_entries);
    for vector in vectors.probes {
        let decision =
            decide_state_action(&vector.probe, manifest.layout_version).expect("valid probe");
        assert_eq!(decision.action, vector.expected_action);
        assert_eq!(decision.reason, vector.expected_reason);
    }
}
