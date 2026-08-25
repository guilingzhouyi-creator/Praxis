//! Independent JSON schema-versioning tests for the Rust kernel.

use l1_kernel_rs::versioning::{
    CHECKPOINT_VERSION, SNAPSHOT_VERSION, VersionErrorCode, VersionRegistry, check_and_migrate,
    reset_versioning, stamp,
};
use serde_json::json;

fn fixture() -> serde_json::Value {
    serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_versioning_vectors.json"
    ))
    .expect("versioning fixture must be valid JSON")
}

#[test]
fn stamp_and_same_version_preserve_json_contract() {
    let registry = VersionRegistry::new();
    let stamped = registry.stamp(json!({"key": "value"}), "snapshot");
    assert_eq!(stamped["_version"], SNAPSHOT_VERSION);
    let checked = registry
        .check_and_migrate(stamped.clone(), "snapshot")
        .expect("same version checks");
    assert_eq!(checked.value, stamped);
    assert!(checked.applied.is_empty());
}

#[test]
fn custom_steps_apply_in_order_and_set_each_version() {
    let registry = VersionRegistry::new();
    registry.register_kind("custom", 3);
    registry
        .register_migration("custom", 1, "one", |mut value| {
            value["one"] = json!(true);
            Ok(value)
        })
        .expect("first migration registers");
    registry
        .register_migration("custom", 2, "two", |mut value| {
            value["two"] = json!(true);
            Ok(value)
        })
        .expect("second migration registers");
    let result = registry
        .check_and_migrate(json!({"_version": 1}), "custom")
        .expect("custom migration succeeds");
    assert_eq!(result.value["_version"], 3);
    assert_eq!(result.value["one"], true);
    assert_eq!(result.value["two"], true);
    assert_eq!(result.applied.len(), 2);
}

#[test]
fn future_unknown_and_invalid_data_fail_closed() {
    let registry = VersionRegistry::new();
    assert_eq!(
        registry
            .check_and_migrate(json!({"_version": 99}), "snapshot")
            .expect_err("future version rejects")
            .code,
        VersionErrorCode::FutureVersion
    );
    let unknown = registry
        .check_and_migrate(json!({"_version": 1}), "unknown")
        .expect("unknown kinds are unchanged");
    assert_eq!(unknown.value["_version"], 1);
    assert_eq!(
        registry
            .check_and_migrate(json!({"_version": -1}), "snapshot")
            .expect_err("negative version rejects")
            .code,
        VersionErrorCode::InvalidData
    );
    assert_eq!(
        registry
            .register_migration("ghost", 1, "nope", Ok)
            .expect_err("unknown kind rejects")
            .code,
        VersionErrorCode::UnknownKind
    );
}

#[test]
fn migration_failures_and_non_object_results_are_structured() {
    let registry = VersionRegistry::new();
    registry.register_kind("custom", 2);
    registry
        .register_migration("custom", 1, "bad", |_| Err("boom".to_owned()))
        .expect("migration registers");
    assert_eq!(
        registry
            .check_and_migrate(json!({"_version": 1}), "custom")
            .expect_err("callback failure rejects")
            .code,
        VersionErrorCode::MigrationFailed
    );
    registry
        .register_migration("custom", 1, "scalar", |_| Ok(json!(1)))
        .expect("replacement migration registers");
    assert_eq!(
        registry
            .check_and_migrate(json!({"_version": 1}), "custom")
            .expect_err("non-object migration rejects")
            .code,
        VersionErrorCode::InvalidData
    );
}

#[test]
fn global_registry_can_be_reset() {
    reset_versioning();
    assert_eq!(
        stamp(json!({}), "checkpoint")["_version"],
        CHECKPOINT_VERSION
    );
    let result = check_and_migrate(json!({"_version": CHECKPOINT_VERSION}), "checkpoint")
        .expect("global registry checks");
    assert!(result.applied.is_empty());
    reset_versioning();
}

#[test]
fn shared_versioning_vectors_match_python_reference() {
    let registry = VersionRegistry::new();
    let vectors = fixture();
    for case in vectors["cases"].as_array().expect("cases array") {
        let kind = case["kind"].as_str().expect("kind string");
        let input = case["input"].clone();
        match case["case"].as_str().expect("case string") {
            "stamp_snapshot" => assert_eq!(registry.stamp(input, kind), case["expect"]),
            "checkpoint_identity_migration" | "unknown_kind" => {
                let result = registry
                    .check_and_migrate(input, kind)
                    .expect("vector migration succeeds");
                assert_eq!(result.value, case["expect"]);
                assert_eq!(
                    serde_json::to_value(result.applied).expect("applied serializes"),
                    case["applied"]
                );
            }
            "future_version" | "missing_zero_migration" => {
                let error = registry
                    .check_and_migrate(input, kind)
                    .expect_err("vector migration rejects");
                let expected = match case["error"].as_str().expect("error string") {
                    "FUTURE_VERSION" => VersionErrorCode::FutureVersion,
                    "MISSING_MIGRATION" => VersionErrorCode::MissingMigration,
                    other => panic!("unexpected fixture error: {other}"),
                };
                assert_eq!(error.code, expected);
            }
            other => panic!("unexpected versioning fixture case: {other}"),
        }
    }
    assert_eq!(registry.current_version("settings"), None);
    assert_eq!(registry.current_version("workspace"), None);
}
