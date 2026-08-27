//! Independent Constitution descriptor mechanism tests for the Rust kernel.

use l1_kernel_rs::rule_descriptor::{CheckResult, RuleDescriptor, RuleSeverity, str_to_severity};
use serde::Deserialize;
use serde_json::json;

#[derive(Debug, Deserialize)]
struct RuleVector {
    severity: Vec<SeverityVector>,
    rule: serde_json::Value,
}

#[derive(Debug, Deserialize)]
struct SeverityVector {
    input: String,
    expected: RuleSeverity,
}

#[test]
fn severity_conversion_and_value_serialization_match_python() {
    let vector: RuleVector = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_rule_descriptor_vectors.json"
    ))
    .expect("rule descriptor fixture must be valid JSON");
    for severity in vector.severity {
        assert_eq!(str_to_severity(&severity.input), severity.expected);
    }
    let rule = RuleDescriptor::new(
        "territory.write",
        "§2.3",
        RuleSeverity::Must,
        "stay inside",
        123.0,
    )
    .with_source("custom")
    .with_tags(["write", "territory"]);
    assert_eq!(rule.to_value(), vector.rule);
    assert_eq!(
        rule.evaluate("write_file", "agent", "/tmp/x", &[]),
        CheckResult::Pass
    );
}

#[test]
fn checker_receives_explicit_context_and_can_warn_or_block() {
    let rule = RuleDescriptor::new("deny.write", "§2", RuleSeverity::Must, "deny", 0.0)
        .with_checker(std::sync::Arc::new(|_, context| {
            if context.action == "write_file" {
                Some(CheckResult::Block)
            } else {
                Some(CheckResult::Warn)
            }
        }));
    assert_eq!(
        rule.evaluate("write_file", "a", "target", &[]),
        CheckResult::Block
    );
    assert_eq!(
        rule.evaluate("read_file", "a", "target", &[]),
        CheckResult::Warn
    );
    assert_eq!(
        serde_json::to_value(CheckResult::Block).unwrap(),
        json!("BLOCK")
    );
}
