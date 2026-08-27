//! Independent value-contract mechanism tests for the Rust kernel.

use l1_kernel_rs::contract::{
    CapabilityResult, Event, EventBusStats, PROCESS_ERROR_EXECUTION,
    PROCESS_RETURN_EXECUTION_ERROR, ProcessOptions, ProcessResult, ProcessState, Signal,
};
use l1_kernel_rs::sync::RwLock;
use serde::Deserialize;
use std::time::Duration;

#[derive(Debug, Deserialize)]
struct ContractVector {
    case: String,
    kind: String,
    value: serde_json::Value,
}

#[test]
fn process_result_matches_python_success_semantics() {
    assert!(ProcessResult::default().ok());
    assert!(
        !ProcessResult {
            returncode: PROCESS_RETURN_EXECUTION_ERROR,
            error_kind: PROCESS_ERROR_EXECUTION.to_owned(),
            ..ProcessResult::default()
        }
        .ok()
    );
}

#[test]
fn process_state_wire_names_are_closed() {
    assert_eq!(ProcessState::Running.as_str(), "RUNNING");
    assert_eq!(ProcessState::parse("ZOMBIE"), Some(ProcessState::Zombie));
    assert_eq!(ProcessState::parse("UNKNOWN"), None);
}

#[test]
fn event_stats_make_overload_explicit() {
    let clean = EventBusStats {
        submitted: 4,
        completed: 4,
        queue_depth: 0,
        ..EventBusStats::default()
    };
    assert!(clean.clean());
    assert_eq!(clean.drop_rate(), 0.0);
    let lossy = EventBusStats {
        submitted: 4,
        completed: 4,
        dropped: 1,
        ..clean
    };
    assert!(!lossy.clean());
    assert_eq!(lossy.dispatch_attempts(), 5);
    assert_eq!(lossy.drop_rate(), 0.2);
}

#[test]
fn unwired_capability_is_fail_closed() {
    let result = CapabilityResult::unwired("read_file");
    assert!(!result.success);
    assert_eq!(result.capability, "read_file");
    assert!(result.error.contains("fail-closed"));
}

#[test]
fn shared_vectors_round_trip_into_rust_contract_types() {
    let vectors: Vec<ContractVector> = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_value_vectors.json"
    ))
    .expect("kernel value fixture must be valid JSON");
    for vector in vectors {
        match vector.kind.as_str() {
            "process_result" => {
                let raw = vector.value;
                let result: ProcessResult = serde_json::from_value(raw.clone()).expect("result");
                assert_eq!(result.ok(), vector.case == "process_success");
                assert_eq!(serde_json::to_value(result).expect("result json"), raw);
            }
            "process_options" => {
                let raw = vector.value;
                let options: ProcessOptions = serde_json::from_value(raw.clone()).expect("options");
                assert_eq!(options.cwd.as_deref(), Some("/tmp"));
                assert_eq!(options.executable.as_deref(), Some("/bin/sh"));
                assert_eq!(serde_json::to_value(options).expect("options json"), raw);
            }
            "process_states" => {
                let raw = vector.value;
                let states: Vec<ProcessState> =
                    serde_json::from_value(raw.clone()).expect("states");
                assert_eq!(states.len(), 5);
                assert_eq!(serde_json::to_value(states).expect("states json"), raw);
            }
            "signal" => {
                let raw = vector.value;
                let signal: Signal = serde_json::from_value(raw.clone()).expect("signal");
                assert_eq!(signal.signal_type, "TASK_DONE");
                assert_eq!(serde_json::to_value(signal).expect("signal json"), raw);
            }
            "event" => {
                let raw = vector.value;
                let event: Event = serde_json::from_value(raw.clone()).expect("event");
                assert_eq!(event.event_type, "tool.completed");
                assert_eq!(serde_json::to_value(event).expect("event json"), raw);
            }
            "event_bus_stats" => {
                let raw = vector.value;
                let stats: EventBusStats = serde_json::from_value(raw.clone()).expect("stats");
                assert_eq!(stats.clean(), vector.case == "event_bus_clean");
                assert_eq!(serde_json::to_value(stats).expect("stats json"), raw);
            }
            "capability_result" => {
                let raw = vector.value;
                let result: CapabilityResult =
                    serde_json::from_value(raw.clone()).expect("capability");
                assert!(!result.success);
                assert!(result.error.contains("fail-closed"));
                assert_eq!(serde_json::to_value(result).expect("capability json"), raw);
            }
            "rwlock" => {
                let raw = vector.value;
                let name = raw["name"].as_str().expect("lock name");
                let agent_id = raw["agent_id"].as_str().expect("agent id");
                let lock = RwLock::new(name, Duration::from_millis(20), Duration::from_millis(1));
                if vector.case == "rwlock_write_reentrant" {
                    assert_eq!(
                        serde_json::to_value(lock.write_lock(agent_id)).expect("first"),
                        raw["first"]
                    );
                    assert_eq!(
                        serde_json::to_value(lock.write_lock(agent_id)).expect("second"),
                        raw["second"]
                    );
                    assert_eq!(
                        serde_json::to_value(lock.unlock(agent_id)).expect("release"),
                        raw["release_once"]
                    );
                    assert_eq!(
                        serde_json::to_value(lock.unlock(agent_id)).expect("release"),
                        raw["release_twice"]
                    );
                } else {
                    assert_eq!(
                        serde_json::to_value(lock.read_lock(agent_id)).expect("read"),
                        raw["read"]
                    );
                    assert_eq!(
                        serde_json::to_value(lock.write_lock(agent_id)).expect("write"),
                        raw["write"]
                    );
                    assert_eq!(
                        serde_json::to_value(lock.unlock(agent_id)).expect("unlock"),
                        raw["unlock"]
                    );
                }
                assert_eq!(
                    serde_json::to_value(lock.status()).expect("status"),
                    raw["status"]
                );
            }
            other => panic!("unknown contract vector kind: {other}"),
        }
    }
}
