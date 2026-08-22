//! Independent GateChain mechanism tests for the Rust kernel.

use l1_kernel_rs::contract::ProcessState;
use l1_kernel_rs::gatechain::{
    GATECHAIN_HISTORY_LIMIT, GateChain, GateDecision, GateIdentity, GateLedger, GateLedgerEntry,
    GateRequest,
};
use serde::Deserialize;

fn ready_identity(ring: u8, verified: bool) -> GateIdentity {
    GateIdentity {
        pid: 7,
        ring,
        state: ProcessState::Ready,
        verified,
    }
}

#[test]
fn empty_whitelist_fails_closed_and_records_block() {
    let chain = GateChain::new();
    let result = chain.check(&GateRequest::new("read_file", "agent-a"));
    assert_eq!(result.decision, GateDecision::Block);
    assert!(!result.allowed);
    assert_eq!(result.steps[0].gate, "G1");
    assert_eq!(chain.ledger().len(), 1);
}

#[test]
fn interactive_identity_skips_process_lookup_but_keeps_gates() {
    let chain = GateChain::new();
    chain.register_tools(["read_file"]);
    let mut request = GateRequest::new("read_file", "shell");
    request.interactive = true;
    let result = chain.check(&request);
    assert!(result.allowed);
    assert_eq!(result.steps[1].result, GateDecision::Pass);
    assert_eq!(result.steps[1].interactive, Some(true));
}

#[test]
fn identity_ring_and_state_fail_closed() {
    let chain = GateChain::new();
    chain.register_tools(["read_file"]);
    let mut request = GateRequest::new("read_file", "agent-a");
    request.identity = Some(ready_identity(2, false));
    assert_eq!(chain.check(&request).decision, GateDecision::Block);
    request.identity = Some(GateIdentity {
        state: ProcessState::Stopped,
        ..ready_identity(1, true)
    });
    assert_eq!(chain.check(&request).decision, GateDecision::Block);
}

#[test]
fn territory_frequency_and_high_danger_inputs_are_structured() {
    let chain = GateChain::new();
    chain.register_tools(["deploy"]);
    let mut request = GateRequest::new("deploy", "agent-a");
    request.identity = Some(ready_identity(1, true));
    request.target = "/project/foo.py".to_owned();
    request.territory = vec!["/project".to_owned()];
    request.timestamp = Some(100.0);
    let blocked = chain.check(&request);
    assert_eq!(blocked.decision, GateDecision::Block);
    assert_eq!(blocked.steps[3].gate, "G4");
    request.pre_approved = true;
    let allowed = chain.check(&request);
    assert!(allowed.allowed);
    assert_eq!(allowed.steps[2].risk_score, Some(5.5));
}

#[test]
fn territory_matching_rejects_prefix_collisions() {
    let chain = GateChain::new();
    chain.register_tools(["read_file"]);
    let mut request = GateRequest::new("read_file", "agent-a");
    request.identity = Some(ready_identity(1, true));
    request.target = "/project/foo_secret/file.py".to_owned();
    request.territory = vec!["/project/foo".to_owned()];
    let result = chain.check(&request);
    assert_eq!(result.decision, GateDecision::Block);
    assert_eq!(result.steps[2].gate, "G3");
}

#[test]
fn low_reputation_blocks_a_g3_frequency_warning() {
    let chain = GateChain::new();
    chain.register_tools(["read_file"]);
    for index in 0..10 {
        chain.ledger().record(GateLedgerEntry {
            agent_id: "agent-a".to_owned(),
            tool: "read_file".to_owned(),
            target: format!("/{index}"),
            result: GateDecision::Pass,
            timestamp: 90.0 + index as f64,
            pattern: "G1-PASS_G3-PASS".to_owned(),
        });
    }
    let mut request = GateRequest::new("read_file", "agent-a");
    request.identity = Some(ready_identity(1, true));
    request.reputation = Some(0.6);
    request.timestamp = Some(100.0);
    let result = chain.check(&request);
    assert_eq!(result.decision, GateDecision::Block);
    assert_eq!(
        result.steps.last().map(|step| step.result),
        Some(GateDecision::Block)
    );
}

#[test]
fn bounded_ledger_recent_count_and_pattern_are_stable() {
    let ledger = GateLedger::with_capacity(2);
    for index in 0..3 {
        ledger.record(GateLedgerEntry {
            agent_id: "a".to_owned(),
            tool: "t".to_owned(),
            target: format!("/{index}"),
            result: GateDecision::Pass,
            timestamp: 100.0 + index as f64,
            pattern: "G1-PASS_G3-PASS".to_owned(),
        });
    }
    assert_eq!(ledger.len(), 2);
    assert_eq!(ledger.recent("a", "t", GATECHAIN_HISTORY_LIMIT).len(), 2);
    assert_eq!(ledger.count("a", "t", 102.0, 60.0), 2);
    ledger.clear();
    assert!(ledger.is_empty());
}

#[derive(Deserialize)]
struct PolicyVector {
    kind: String,
    tools: Option<Vec<String>>,
    input: serde_json::Value,
    history_count: Option<usize>,
    expect: PolicyExpectation,
}

#[derive(Deserialize)]
struct PolicyExpectation {
    allowed: bool,
    decision: String,
    blocked_gate: Option<String>,
}

#[test]
fn shared_policy_vectors_match_gatechain_candidate() {
    let vectors: Vec<PolicyVector> = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_policy_vectors.json"
    ))
    .expect("policy fixture must be valid JSON");
    for vector in vectors
        .into_iter()
        .filter(|vector| vector.kind == "gatechain")
    {
        let chain = GateChain::new();
        chain.replace_tools(vector.tools.unwrap_or_default());
        let input: GateRequest = serde_json::from_value(vector.input).expect("request");
        for index in 0..vector.history_count.unwrap_or(0) {
            chain.ledger().record(GateLedgerEntry {
                agent_id: input.agent_id.clone(),
                tool: input.tool.clone(),
                target: String::new(),
                result: GateDecision::Pass,
                timestamp: 90.0 + index as f64,
                pattern: "G1-PASS_G3-PASS".to_owned(),
            });
        }
        let result = chain.check(&input);
        assert_eq!(result.allowed, vector.expect.allowed);
        assert_eq!(result.decision.as_str(), vector.expect.decision);
        if let Some(expected_gate) = vector.expect.blocked_gate {
            assert_eq!(
                result
                    .steps
                    .iter()
                    .find(|step| step.result == GateDecision::Block)
                    .map(|step| step.gate.as_str()),
                Some(expected_gate.as_str())
            );
        }
    }
}
