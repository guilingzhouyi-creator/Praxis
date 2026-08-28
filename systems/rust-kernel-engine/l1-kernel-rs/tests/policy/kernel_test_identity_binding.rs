//! Independent identity-binding mechanism tests for the Rust kernel.

use l1_kernel_rs::identity_binding::{
    BindingPolicy, BindingSpec, IdentityBindingRegistry, IdentityBindingStore,
    IdentityBindingStoreError, WritePrincipal,
};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

#[test]
fn write_gate_is_explicit_and_fail_closed() {
    let registry = IdentityBindingRegistry::default();
    assert!(
        registry
            .authorize_write(&WritePrincipal::external("", "", 0))
            .is_err()
    );
    assert!(
        registry
            .authorize_write(&WritePrincipal::external("agent", "scout", 1))
            .is_err()
    );
    assert!(
        registry
            .authorize_write(&WritePrincipal::external("agent", "deployer", 1))
            .is_ok()
    );
    assert!(
        registry
            .authorize_write(&WritePrincipal::internal())
            .is_ok()
    );
}

#[test]
fn upsert_bounds_metadata_and_preserves_identity_id() {
    let registry = IdentityBindingRegistry::default();
    let principal = WritePrincipal::internal();
    let mut spec = BindingSpec::new("cell-1", "writer", "id-first");
    spec.domain_tags = vec!["review".to_owned(), "build".to_owned(), "review".to_owned()];
    spec.max_chars = usize::MAX;
    let first = registry.upsert(spec, &principal).expect("first binding");
    assert_eq!(first.identity_id, "id-first");
    assert_eq!(first.domain_tags, ["build", "review"]);
    assert_eq!(first.max_chars, 1_200);
    let second = registry
        .upsert(BindingSpec::new("cell-1", "writer", ""), &principal)
        .expect("rebind");
    assert_eq!(second.identity_id, "id-first");
    assert_eq!(second.revision, 2);
}

#[test]
fn capacity_and_lifecycle_are_bounded() {
    let policy = BindingPolicy {
        max_bindings_per_cell: 1,
        ..BindingPolicy::default()
    };
    let registry = IdentityBindingRegistry::new(policy).expect("valid policy");
    let principal = WritePrincipal::internal();
    registry
        .upsert(BindingSpec::new("cell-1", "writer", "id-1"), &principal)
        .expect("first binding");
    assert!(
        registry
            .upsert(BindingSpec::new("cell-1", "reader", "id-2"), &principal)
            .is_err()
    );
    assert_eq!(registry.cell_ids(), ["cell-1"]);
    assert_eq!(registry.unbind("cell-1", "writer", &principal), Ok(true));
    assert_eq!(registry.unbind("cell-1", "writer", &principal), Ok(false));
    assert_eq!(registry.clear_cell("cell-1", &principal), Ok(0));
}

#[test]
fn snapshots_are_deterministic_and_serde_round_trips() {
    let registry = IdentityBindingRegistry::default();
    let principal = WritePrincipal::internal();
    registry
        .upsert(BindingSpec::new("cell-b", "writer", "id-b"), &principal)
        .expect("binding b");
    registry
        .upsert(BindingSpec::new("cell-a", "reader", "id-a"), &principal)
        .expect("binding a");
    let snapshot = registry.snapshot();
    assert_eq!(snapshot[0].cell_id, "cell-a");
    let encoded = serde_json::to_string(&snapshot).expect("snapshot serializes");
    let decoded: Vec<l1_kernel_rs::identity_binding::BindingRecord> =
        serde_json::from_str(&encoded).expect("snapshot parses");
    assert_eq!(decoded, snapshot);
}

#[test]
fn persistent_store_round_trips_metadata_without_prompt_payloads() {
    let path = unique_checkpoint_path("roundtrip");
    let principal = WritePrincipal::internal();
    {
        let store = IdentityBindingStore::open(&path, BindingPolicy::default()).expect("open");
        let mut spec = BindingSpec::new("cell-1", "writer", "id-1");
        spec.domain_tags = vec!["z".to_owned(), "a".to_owned()];
        store.upsert(spec, &principal).expect("persist binding");
        assert_eq!(store.revision(), 1);
    }

    let reopened =
        IdentityBindingStore::open(&path, BindingPolicy::default()).expect("reopen checkpoint");
    assert_eq!(reopened.revision(), 1);
    assert_eq!(
        reopened
            .get("cell-1", "writer")
            .expect("restored record")
            .domain_tags,
        ["a", "z"]
    );
    let checkpoint = fs::read_to_string(&path).expect("checkpoint bytes");
    assert!(!checkpoint.contains("prompt_fragment"));
    assert!(!checkpoint.contains("definition"));
    cleanup_checkpoint(&path);
}

#[test]
fn malformed_checkpoint_is_rejected_before_registry_mutation() {
    let path = unique_checkpoint_path("invalid");
    fs::write(
        &path,
        r#"{"document_version":1,"revision":1,"records":[{"cell_id":"cell-1","role":"writer","identity_id":"id-1","domain_tags":["z","a"],"max_chars":1200,"revision":1,"updated_by":"internal"}]}"#,
    )
    .expect("write invalid checkpoint");
    let error = match IdentityBindingStore::open(&path, BindingPolicy::default()) {
        Ok(_) => panic!("unsorted tags must fail closed"),
        Err(error) => error,
    };
    assert!(matches!(
        error,
        IdentityBindingStoreError::InvalidDocument { .. }
    ));
    cleanup_checkpoint(&path);
}

#[test]
fn failed_atomic_replacement_rolls_back_memory_and_cleans_temporary_file() {
    let path = unique_checkpoint_path("rollback");
    let store = IdentityBindingStore::open(&path, BindingPolicy::default()).expect("open");
    fs::create_dir(&path).expect("block replacement with directory");
    let error = store
        .upsert(
            BindingSpec::new("cell-1", "writer", "id-1"),
            &WritePrincipal::internal(),
        )
        .expect_err("directory target must reject replacement");
    assert!(matches!(error, IdentityBindingStoreError::Io(_)));
    assert_eq!(store.revision(), 0);
    assert!(store.snapshot().is_empty());
    let parent = path.parent().expect("parent");
    let temp_prefix = format!(".{}.tmp-", path.file_name().unwrap().to_string_lossy());
    assert!(
        fs::read_dir(parent)
            .expect("read parent")
            .filter_map(Result::ok)
            .all(|entry| !entry
                .file_name()
                .to_string_lossy()
                .starts_with(&temp_prefix))
    );
    fs::remove_dir(&path).expect("cleanup directory");
}

fn unique_checkpoint_path(label: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "praxis-identity-binding-{label}-{}-{nonce}.json",
        std::process::id()
    ))
}

fn cleanup_checkpoint(path: &PathBuf) {
    let _ = fs::remove_file(path);
}
