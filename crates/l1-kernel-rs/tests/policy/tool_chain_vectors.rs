//! Cross-language contract tests for the Rust tool-call fingerprint candidate.

use l1_kernel_rs::tool_chain::{
    FingerprintLink, VerificationResult, compute_fingerprint, normalize_call_data,
    verify_fingerprint_chain,
};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct ToolChainVectors {
    secret_key: String,
    cases: Vec<ToolChainCase>,
}

#[derive(Debug, Deserialize)]
struct ToolChainCase {
    links: Vec<ToolChainLink>,
    expected: VerificationResult,
}

#[derive(Debug, Deserialize)]
struct ToolChainLink {
    call_id: String,
    tool_name: String,
    agent_id: String,
    ring: i64,
    parent_id: String,
    depth: usize,
    normalized: String,
    fingerprint: String,
    #[serde(default)]
    canonical_fingerprint: Option<String>,
}

#[test]
fn shared_tool_chain_vectors_match_public_candidate_api() {
    let vectors: ToolChainVectors = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_tool_chain_vectors.json"
    ))
    .expect("valid tool-chain vectors");
    let key = vectors.secret_key.into_bytes();
    for case in vectors.cases {
        let mut previous = String::new();
        let mut links = Vec::with_capacity(case.links.len());
        for link in case.links {
            assert_eq!(
                normalize_call_data(
                    &link.tool_name,
                    &link.agent_id,
                    link.ring,
                    &link.call_id,
                    &link.parent_id,
                    link.depth,
                ),
                link.normalized
            );
            assert_eq!(
                compute_fingerprint(&key, &link.normalized, &previous),
                link.canonical_fingerprint
                    .as_deref()
                    .unwrap_or(&link.fingerprint)
            );
            previous = link.fingerprint.clone();
            links.push(FingerprintLink {
                call_id: link.call_id,
                tool_name: link.tool_name,
                agent_id: link.agent_id,
                ring: link.ring,
                parent_id: link.parent_id,
                depth: link.depth,
                fingerprint: link.fingerprint,
            });
        }
        assert_eq!(verify_fingerprint_chain(&key, &links), case.expected);
    }
}
