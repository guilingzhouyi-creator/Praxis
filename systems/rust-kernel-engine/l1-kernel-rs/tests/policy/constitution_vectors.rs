//! Cross-language contract tests for Constitution rule snapshots.

use l1_kernel_rs::constitution::{ConstitutionEngine, ConstitutionRule};
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct ConstitutionVectors {
    valid_rules: Vec<ConstitutionRule>,
    expected_ids: Vec<String>,
    expected_tags: std::collections::BTreeMap<String, Vec<String>>,
    invalid_rules: Vec<InvalidRule>,
    duplicate_id: String,
}

#[derive(Debug, Deserialize)]
struct InvalidRule {
    rule: ConstitutionRule,
    error: String,
}

#[test]
fn shared_constitution_rule_vectors_are_validated_and_normalized() {
    let vectors: ConstitutionVectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_constitution_vectors.json"
    ))
    .expect("valid constitution vectors");
    let engine = ConstitutionEngine::new();
    engine
        .replace_rules_checked(vectors.valid_rules)
        .expect("valid custom rules");
    let rules = engine.rules();
    assert_eq!(
        rules.iter().map(|rule| rule.id.clone()).collect::<Vec<_>>(),
        vectors.expected_ids
    );
    for rule in rules {
        assert_eq!(
            rule.tags,
            vectors
                .expected_tags
                .get(&rule.id)
                .expect("expected tags")
                .clone()
        );
    }

    for invalid in vectors.invalid_rules {
        let actual = engine
            .replace_rules_checked(vec![invalid.rule])
            .expect_err("invalid rule must fail closed");
        assert_eq!(actual, invalid.error);
    }

    let duplicate: ConstitutionRule = serde_json::from_value(serde_json::json!({
        "id": vectors.duplicate_id,
        "section": "custom.duplicate",
        "severity": "MAY",
        "description": "duplicate",
        "kind": "noop",
        "source": "custom",
        "tags": []
    }))
    .expect("duplicate rule is structurally valid");
    let existing = engine.rules();
    assert_eq!(
        engine
            .replace_rules_checked(vec![existing[0].clone(), duplicate])
            .expect_err("duplicate ids must fail closed"),
        "constitution rule id must be unique"
    );
    assert_eq!(
        engine.rules(),
        existing,
        "failed replacement preserves snapshot"
    );

    let serialized: Vec<Value> = engine
        .rules()
        .into_iter()
        .map(|rule| serde_json::to_value(rule).expect("rule serializes"))
        .collect();
    assert!(serialized.iter().all(|rule| rule["source"] == "custom"));
}
