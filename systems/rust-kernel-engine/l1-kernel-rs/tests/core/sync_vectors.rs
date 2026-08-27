//! Cross-language contract tests for the Rust synchronization candidate.

use std::time::Duration;

use l1_kernel_rs::sync::RwLock;
use serde::Deserialize;
use serde_json::Value;

#[derive(Debug, Deserialize)]
struct SyncVectors {
    cases: Vec<SyncCase>,
}

#[derive(Debug, Deserialize)]
struct SyncCase {
    name: String,
    lock_name: String,
    timeout_ms: u64,
    operations: Vec<SyncOperation>,
}

#[derive(Debug, Deserialize)]
struct SyncOperation {
    kind: String,
    agent: String,
    expected: Value,
    status: Value,
}

#[test]
fn shared_rwlock_vectors_match_public_candidate_api() {
    let vectors: SyncVectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_sync_vectors.json"
    ))
    .expect("valid sync vectors");
    for case in vectors.cases {
        let lock = RwLock::new(
            case.lock_name,
            Duration::from_millis(case.timeout_ms),
            Duration::ZERO,
        );
        for operation in case.operations {
            let actual = match operation.kind.as_str() {
                "read" => lock.read_lock(&operation.agent),
                "write" => lock.write_lock(&operation.agent),
                "unlock" => lock.unlock(&operation.agent),
                other => panic!("unknown sync operation: {other}"),
            };
            assert_eq!(
                serde_json::to_value(actual).expect("sync response is serializable"),
                operation.expected,
                "{}",
                case.name
            );
            assert_eq!(
                serde_json::to_value(lock.status()).expect("sync status is serializable"),
                operation.status,
                "{}",
                case.name
            );
        }
    }
}
