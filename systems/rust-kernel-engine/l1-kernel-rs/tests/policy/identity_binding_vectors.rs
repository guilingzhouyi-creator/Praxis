//! Cross-language control vectors for the Rust identity-binding candidate.

use l1_kernel_rs::identity_binding::{BindingSpec, IdentityBindingRegistry, WritePrincipal};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct IdentityBindingVectors {
    authorization: Vec<AuthorizationCase>,
    mutations: Vec<MutationCase>,
    expected_revision: u64,
    expected_cells: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct AuthorizationCase {
    agent_id: String,
    role: String,
    #[serde(default)]
    internal: bool,
    allowed: bool,
}

#[derive(Debug, Deserialize)]
struct MutationCase {
    kind: String,
    cell_id: String,
    role: String,
    #[serde(default)]
    identity_id: String,
    #[serde(default)]
    internal: bool,
    expected: Option<bool>,
    expected_count: Option<usize>,
}

fn principal(case: &MutationCase) -> WritePrincipal {
    if case.internal {
        WritePrincipal::internal()
    } else {
        WritePrincipal::external(&case.identity_id, &case.role, 0)
    }
}

#[test]
fn shared_identity_binding_vectors_match_rust_candidate() {
    let vectors: IdentityBindingVectors = serde_json::from_str(include_str!(
        "../../../../../tests/fixtures/kernel_identity_binding_vectors.json"
    ))
    .expect("valid identity-binding vectors");
    let registry = IdentityBindingRegistry::default();

    for case in &vectors.authorization {
        let principal = if case.internal {
            WritePrincipal::internal()
        } else {
            WritePrincipal::external(&case.agent_id, &case.role, 0)
        };
        assert_eq!(registry.authorize_write(&principal).is_ok(), case.allowed);
    }

    for case in &vectors.mutations {
        let principal = principal(case);
        match case.kind.as_str() {
            "upsert" => {
                let result = registry.upsert(
                    BindingSpec::new(&case.cell_id, &case.role, &case.identity_id),
                    &principal,
                );
                assert_eq!(result.is_ok(), case.expected.expect("upsert expectation"));
            }
            "unbind" => {
                assert_eq!(
                    registry
                        .unbind(&case.cell_id, &case.role, &principal)
                        .expect("unbind operation"),
                    case.expected.expect("unbind expectation")
                );
            }
            "clear" => {
                assert_eq!(
                    registry
                        .clear_cell(&case.cell_id, &principal)
                        .expect("clear operation"),
                    case.expected_count.expect("clear expectation")
                );
            }
            other => panic!("unknown identity-binding operation: {other}"),
        }
    }

    assert_eq!(registry.revision(), vectors.expected_revision);
    assert_eq!(registry.cell_ids(), vectors.expected_cells);
}
