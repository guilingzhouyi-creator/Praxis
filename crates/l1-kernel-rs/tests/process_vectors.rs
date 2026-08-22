//! Cross-language contract tests for the Rust process-table candidate.

use l1_kernel_rs::process::{ProcessTable, ProcessTableConfig, WireMap};
use l1_kernel_rs::substrate::ProcessHandle;
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Debug, Deserialize)]
struct ProcessVectors {
    cases: Vec<ProcessCase>,
}

#[derive(Debug, Deserialize)]
struct ProcessCase {
    name: String,
    audit_max: usize,
    operations: Vec<ProcessOperation>,
    expected: ProcessExpected,
}

#[derive(Debug, Deserialize)]
struct ProcessOperation {
    kind: String,
    name: Option<String>,
    role: Option<String>,
    parent_pid: Option<u64>,
    ring: Option<u8>,
    pid: Option<u64>,
    allocated: Option<u64>,
    used: Option<u64>,
    tokens: Option<u64>,
    delta: Option<i64>,
    seconds: Option<f64>,
    cpu_seconds: Option<f64>,
    reason: Option<String>,
    exit_code: Option<i32>,
    result: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct ProcessExpected {
    agent: Option<Value>,
    is_cancelled: Option<bool>,
    final_set_running: Option<bool>,
    before_reap: Option<Value>,
    after_reap_exists: Option<bool>,
    resource_summary: Value,
    audit: Value,
}

fn project_pcb(table: &ProcessTable, name: &str) -> Value {
    let pcb = table.get_by_name(name).expect("expected process exists");
    json!({
        "pid": pcb.pid,
        "name": pcb.name,
        "role": pcb.role,
        "parent_pid": pcb.parent_pid,
        "ring": pcb.ring,
        "state": pcb.state.as_str(),
        "identity_verified": pcb.identity_verified,
        "cancelled": pcb.cancelled,
        "cancel_reason": pcb.cancel_reason,
        "exit_code": pcb.exit_code,
        "exit_reason": pcb.exit_reason,
        "resources": {
            "tokens_allocated": pcb.resources.tokens_allocated,
            "tokens_used": pcb.resources.tokens_used,
            "workers_active": pcb.resources.workers_active,
            "scouts_active": pcb.resources.scouts_active,
            "memory_entries": pcb.resources.memory_entries,
            "cards_processed": pcb.resources.cards_processed,
            "cpu_time": pcb.resources.cpu_time,
        }
    })
}

fn project_audit(rows: Vec<WireMap>) -> Value {
    Value::Array(
        rows.into_iter()
            .map(|mut row| {
                row.remove("timestamp");
                serde_json::to_value(row).expect("audit row serializes")
            })
            .collect(),
    )
}

#[test]
fn shared_process_vectors_match_public_candidate_api() {
    let vectors: ProcessVectors = serde_json::from_str(include_str!(
        "../../../tests/fixtures/kernel_process_vectors.json"
    ))
    .expect("valid process vectors");
    for case in vectors.cases {
        let table = ProcessTable::new(ProcessTableConfig::new(
            case.audit_max,
            "kernel",
            "init",
            3,
            1,
        ));
        let mut before_reap = None;
        for operation in case.operations {
            let name = operation.name.as_deref().unwrap_or("");
            match operation.kind.as_str() {
                "spawn" => {
                    let pcb = table.spawn(
                        name,
                        operation.role.as_deref().unwrap_or(""),
                        operation.parent_pid.unwrap_or(0),
                        operation.ring,
                    );
                    assert_eq!(pcb.pid, operation.pid.unwrap_or(0), "{}", case.name);
                }
                "mark_identity_verified" => assert!(table.mark_identity_verified(name)),
                "record_tokens" => assert!(table.record_tokens(
                    operation.pid.unwrap_or(0),
                    operation.allocated.unwrap_or(0),
                    operation.used.unwrap_or(0)
                )),
                "record_card" => assert!(table.record_card(operation.pid.unwrap_or(0))),
                "record_scout" => assert!(
                    table.record_scout(operation.pid.unwrap_or(0), operation.delta.unwrap_or(0))
                ),
                "record_cpu" => assert!(
                    table.record_cpu(operation.pid.unwrap_or(0), operation.seconds.unwrap_or(0.0))
                ),
                "record_alloc" => assert!(
                    table.record_alloc(operation.pid.unwrap_or(0), operation.tokens.unwrap_or(0))
                ),
                "record_use" => assert!(table.record_use(
                    operation.pid.unwrap_or(0),
                    operation.tokens.unwrap_or(0),
                    operation.cpu_seconds.unwrap_or(0.0)
                )),
                "set_running" => {
                    let expected = operation.result.unwrap_or(false);
                    assert_eq!(table.set_running(name), expected, "{}", case.name);
                }
                "yield" => assert!(table.yield_process(name)),
                "cancel" => assert!(table.cancel(name, operation.reason.as_deref().unwrap_or(""))),
                "exit_by_name" => assert!(table.exit_by_name(
                    name,
                    operation.exit_code.unwrap_or(0),
                    operation.reason.as_deref().unwrap_or("")
                )),
                "reap" => {
                    let pid = operation.pid.unwrap_or(0);
                    let pcb = table.get(pid).expect("process exists before reap");
                    before_reap = Some(project_pcb(&table, &pcb.name));
                    assert!(table.reap(pid).is_some());
                }
                other => panic!("unknown process operation: {other}"),
            }
        }

        if let Some(before) = before_reap {
            let expected = case.expected.before_reap.expect("before reap expectation");
            for key in ["pid", "name", "state", "exit_code", "exit_reason"] {
                assert_eq!(before[key], expected[key], "{}", case.name);
            }
            assert_eq!(case.expected.after_reap_exists, Some(false));
            assert!(
                table
                    .get_by_name(expected["name"].as_str().unwrap())
                    .is_none()
            );
        } else {
            let expected_agent = case.expected.agent.expect("agent expectation");
            let agent_name = expected_agent["name"].as_str().unwrap();
            assert_eq!(
                project_pcb(&table, agent_name),
                expected_agent,
                "{}",
                case.name
            );
            assert_eq!(
                table.is_cancelled(agent_name),
                case.expected.is_cancelled.unwrap_or(false),
                "{}",
                case.name
            );
            assert_eq!(
                table.set_running(agent_name),
                case.expected.final_set_running.unwrap_or(false),
                "{}",
                case.name
            );
        }
        assert_eq!(
            serde_json::to_value(table.resource_summary()).expect("summary serializes"),
            case.expected.resource_summary,
            "{}",
            case.name
        );
        assert_eq!(
            project_audit(table.audit_log(20)),
            case.expected.audit,
            "{}",
            case.name
        );
    }
}

#[test]
fn typed_process_handle_boundary_rejects_stale_generation() {
    let table = ProcessTable::new(ProcessTableConfig::new(8, "kernel", "init", 3, 1));
    let pcb = table.spawn("agent-handle", "worker", 0, None);
    let handle = table.handle_for_pid(pcb.pid).expect("live handle");
    assert_eq!(table.get_by_handle(handle).expect("lookup").pid, pcb.pid);
    let stale = ProcessHandle::new(handle.slot(), 2).expect("stale generation");
    assert!(table.get_by_handle(stale).is_none());
    assert!(table.exit_handle(handle, 0, "done"));
    assert!(table.reap_handle(handle).is_some());
    assert!(table.get_by_handle(handle).is_none());
}
