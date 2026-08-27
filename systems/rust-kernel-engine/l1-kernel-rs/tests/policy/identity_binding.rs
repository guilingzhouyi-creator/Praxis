//! Independent identity-binding mechanism tests for the Rust kernel.

use l1_kernel_rs::identity_binding::{
    BindingPolicy, BindingSpec, IdentityBindingRegistry, WritePrincipal,
};

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
