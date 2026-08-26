//! Independent lifecycle mechanism tests for the Rust kernel.

use l1_kernel_rs::lifecycle::{
    LifecycleErrorCode, LifecycleRecord, LifecycleRegistry, LifecycleState, reset_lifecycle, state,
};
use serde_json::Value;

fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_lifecycle_vectors.json"
    ))
    .expect("lifecycle fixture must be valid JSON")
}

#[test]
fn transition_graph_matches_python_lifecycle_contract() {
    let lifecycle = LifecycleRegistry::new();
    assert_eq!(lifecycle.state(), LifecycleState::Halted);
    assert!(!lifecycle.transition(LifecycleState::Active));
    assert!(lifecycle.transition(LifecycleState::Installing));
    assert!(lifecycle.transition(LifecycleState::Booting));
    assert!(lifecycle.transition(LifecycleState::Active));
    assert!(lifecycle.transition(LifecycleState::Draining));
    assert!(lifecycle.transition(LifecycleState::Halted));
    assert!(!lifecycle.transition(LifecycleState::Crashed));
}

#[test]
fn crash_recovery_and_shutdown_paths_are_explicit() {
    let lifecycle = LifecycleRegistry::new();
    assert!(lifecycle.transition(LifecycleState::Booting));
    assert!(lifecycle.transition(LifecycleState::Crashed));
    assert!(lifecycle.transition(LifecycleState::Booting));
    assert!(lifecycle.transition(LifecycleState::Active));
    let mut record = lifecycle.snapshot();
    record.install_version = 1;
    record.schema_version = "schema-1".to_owned();
    lifecycle.restore(record).expect("restore");
    lifecycle.record_boot_success_at("boot-1");
    lifecycle.record_shutdown_at(false, "shutdown-1");
    assert!(lifecycle.should_install("schema-1"));
    lifecycle.record_shutdown_at(true, "shutdown-2");
    assert!(!lifecycle.should_install("schema-1"));
    assert!(lifecycle.should_install("schema-2"));
}

#[test]
fn record_round_trip_and_invalid_restore_fail_closed() {
    let lifecycle = LifecycleRegistry::new();
    let mut record = LifecycleRecord {
        install_version: 2,
        schema_version: "schema-1".to_owned(),
        app_version: "kernel-1".to_owned(),
        ..LifecycleRecord::default()
    };
    record.lifecycle_state = LifecycleState::Active.as_str().to_owned();
    lifecycle.restore(record.clone()).expect("restore");
    let encoded = lifecycle.encode().expect("encode");
    let restored = LifecycleRegistry::new();
    restored.restore_encoded(&encoded).expect("decode");
    assert_eq!(restored.snapshot(), record);
    record.lifecycle_state = "unknown".to_owned();
    let error = restored.restore(record).expect_err("invalid state");
    assert_eq!(error.code, LifecycleErrorCode::InvalidState);
    assert_eq!(restored.state(), LifecycleState::Active);
}

#[test]
fn malformed_checkpoint_is_structured() {
    let lifecycle = LifecycleRegistry::new();
    let error = lifecycle
        .restore_encoded(b"not-json")
        .expect_err("invalid record");
    assert_eq!(error.code, LifecycleErrorCode::InvalidRecord);
}

#[test]
fn global_lifecycle_can_be_reset() {
    reset_lifecycle();
    assert_eq!(state(), LifecycleState::Halted);
    assert!(l1_kernel_rs::lifecycle::transition(LifecycleState::Booting));
    reset_lifecycle();
    assert_eq!(state(), LifecycleState::Halted);
}

#[test]
fn shared_lifecycle_vectors_match_python_reference() {
    let vectors = fixture();
    for path in vectors["paths"].as_array().expect("paths") {
        let lifecycle = LifecycleRegistry::new();
        let states = path["states"].as_array().expect("states");
        for value in states.iter().skip(1) {
            let target =
                LifecycleState::parse(value.as_str().expect("state")).expect("known state");
            assert!(lifecycle.transition(target));
        }
        let expected =
            LifecycleState::parse(states.last().expect("last state").as_str().expect("state"))
                .expect("known state");
        assert_eq!(lifecycle.state(), expected);
    }
    for invalid in vectors["invalid_transitions"]
        .as_array()
        .expect("invalid transitions")
    {
        let lifecycle = LifecycleRegistry::new();
        let source =
            LifecycleState::parse(invalid["from"].as_str().expect("from")).expect("source");
        let target = LifecycleState::parse(invalid["to"].as_str().expect("to")).expect("target");
        match source {
            LifecycleState::Halted => {}
            LifecycleState::Active => {
                assert!(lifecycle.transition(LifecycleState::Booting));
                assert!(lifecycle.transition(LifecycleState::Active));
            }
            LifecycleState::Draining => {
                assert!(lifecycle.transition(LifecycleState::Booting));
                assert!(lifecycle.transition(LifecycleState::Active));
                assert!(lifecycle.transition(LifecycleState::Draining));
            }
            LifecycleState::Crashed => {
                assert!(lifecycle.transition(LifecycleState::Booting));
                assert!(lifecycle.transition(LifecycleState::Crashed));
            }
            LifecycleState::Installing | LifecycleState::Booting => unreachable!(),
        }
        assert_eq!(lifecycle.state(), source);
        assert!(!lifecycle.transition(target));
    }
    for case in vectors["install_decisions"]
        .as_array()
        .expect("install decisions")
    {
        let record: LifecycleRecord =
            serde_json::from_value(case["record"].clone()).expect("record");
        let lifecycle = LifecycleRegistry::from_record(record).expect("lifecycle");
        assert_eq!(
            lifecycle.should_install(case["current_schema"].as_str().expect("schema")),
            case["should_install"].as_bool().expect("decision")
        );
    }
}
