//! Independent Constitution mechanism tests for the Rust kernel.

use l1_kernel_rs::constitution::{
    CheckResult, ConstitutionEngine, ConstitutionInput, ConstitutionRule, RuleSeverity,
};
use serde::Deserialize;

#[test]
fn default_rules_are_indexed_and_safe_for_read() {
    let engine = ConstitutionEngine::new();
    let input = ConstitutionInput::new("read_file", "agent-a");
    assert!(
        engine
            .check(&input)
            .iter()
            .all(|report| report.result != CheckResult::Block)
    );
    assert!(engine.rules().len() >= 16);
}

#[test]
fn territory_and_constitution_targets_block() {
    let engine = ConstitutionEngine::new();
    let mut input = ConstitutionInput::new("read_file", "agent-a");
    input.target = "/project/outside.py".to_owned();
    input.territory = vec!["/project/src".to_owned()];
    assert_eq!(engine.is_allowed(&input).decision, "block");
    input.action = "write_file".to_owned();
    input.target = "/project/.praxis-rules.md".to_owned();
    input.territory.clear();
    assert_eq!(engine.is_allowed(&input).decision, "block");
}

#[test]
fn sandbox_and_gatechain_rules_warn_without_blocking() {
    let engine = ConstitutionEngine::new();
    let mut input = ConstitutionInput::new("write_file", "agent-a");
    input.target = "/outside/file.py".to_owned();
    let decision = engine.is_allowed(&input);
    assert!(decision.allowed);
    assert!(decision.warns >= 1);
    input.action = "run_in_terminal".to_owned();
    let decision = engine.is_allowed(&input);
    assert!(decision.allowed);
    assert!(decision.warns >= 1);
}

#[test]
fn scout_and_offensive_skill_rules_fail_closed() {
    let engine = ConstitutionEngine::new();
    let mut scout = ConstitutionInput::new("write_file", "scout");
    assert_eq!(engine.is_allowed(&scout).decision, "block");
    scout.action = "use_skill".to_owned();
    scout.offensive_skill = true;
    assert_eq!(engine.is_allowed(&scout).decision, "block");
    scout.full_power = true;
    assert!(engine.is_allowed(&scout).allowed);
}

#[test]
fn custom_rules_round_trip_and_replace_without_io() {
    let engine = ConstitutionEngine::new();
    let custom = ConstitutionRule::custom("custom.one", "§custom", RuleSeverity::Should, "test");
    engine.replace_rules(vec![custom.clone()]);
    assert_eq!(engine.rules(), vec![custom]);
    assert!(
        engine
            .check(&ConstitutionInput::new("read_file", "agent"))
            .is_empty()
    );
    let encoded = serde_json::to_string(&engine.rules()).expect("rules serialize");
    assert!(encoded.contains("custom.one"));
}

#[test]
fn cross_territory_shared_action_blocks() {
    let engine = ConstitutionEngine::new();
    let mut input = ConstitutionInput::new("write_file", "agent-a");
    input.territory = vec!["/shared/unit".to_owned()];
    let decision = engine.is_allowed(&input);
    assert_eq!(decision.decision, "block");
}

#[derive(Deserialize)]
struct PolicyVector {
    kind: String,
    input: serde_json::Value,
    expect: PolicyExpectation,
}

#[derive(Deserialize)]
struct PolicyExpectation {
    allowed: bool,
    decision: String,
}

#[test]
fn shared_policy_vectors_match_constitution_candidate() {
    let vectors: Vec<PolicyVector> = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_policy_vectors.json"
    ))
    .expect("policy fixture must be valid JSON");
    let engine = ConstitutionEngine::new();
    for vector in vectors
        .into_iter()
        .filter(|vector| vector.kind == "constitution")
    {
        let input: ConstitutionInput = serde_json::from_value(vector.input).expect("input");
        let result = engine.is_allowed(&input);
        assert_eq!(result.allowed, vector.expect.allowed);
        assert_eq!(result.decision, vector.expect.decision);
    }
}
