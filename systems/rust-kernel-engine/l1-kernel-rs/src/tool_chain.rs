//! Provider-neutral tool-call fingerprint chaining candidate.
//!
//! This module only normalizes explicit call fields, computes HMAC fingerprints,
//! and verifies a root-first chain. Key provisioning, call storage, trimming,
//! and runtime tool execution remain Python-owned adapter responsibilities.

use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

/// Number of hexadecimal characters retained from each SHA-256 digest.
pub const FINGERPRINT_HEX_LENGTH: usize = 40;

/// Explicit call fields used to derive one chain link.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FingerprintLink {
    /// Stable call identifier.
    /// Unique tool-call id.
    /// Verified call id.
    pub call_id: String,
    /// Tool name supplied by the caller.
    /// Invoked tool name.
    pub tool_name: String,
    /// Agent identifier supplied by the caller.
    /// Calling agent identity.
    pub agent_id: String,
    /// Execution ring supplied by the caller.
    /// Authority ring of the call.
    pub ring: i64,
    /// Parent call identifier, empty for a root.
    /// Parent call id (GENESIS at the root).
    pub parent_id: String,
    /// Depth supplied by the chain owner.
    /// Chain depth from the root call.
    /// Depth recorded in the chain.
    /// Verified chain depth.
    pub depth: usize,
    /// Stored fingerprint to validate.
    /// Truncated HMAC-SHA256 chain fingerprint.
    pub fingerprint: String,
}

/// One stable verification step in the public wire shape.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VerificationStep {
    /// Call identifier checked by this step.
    pub call_id: String,
    /// Tool name retained for audit display.
    /// Tool name recorded in the chain.
    pub tool: String,
    /// Declared chain depth.
    pub depth: usize,
    /// Whether the stored fingerprint matched the recomputed value.
    /// Whether recomputation matched the stored link.
    pub fingerprint_match: bool,
}

/// Result of verifying a root-first fingerprint chain.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VerificationResult {
    /// Whether every chain step matched.
    /// Overall chain validity verdict.
    pub valid: bool,
    /// Per-link verification details.
    /// Root-first per-link verification steps.
    pub steps: Vec<VerificationStep>,
    /// Number of links checked.
    pub depth: usize,
}

/// Render call fields in the language-neutral fingerprint format.
pub fn normalize_call_data(
    tool_name: &str,
    agent_id: &str,
    ring: i64,
    call_id: &str,
    parent_id: &str,
    depth: usize,
) -> String {
    format!("{tool_name}:{agent_id}:{ring}:{call_id}:{parent_id}:{depth}")
}

/// Compute a truncated HMAC-SHA256 fingerprint with a GENESIS fallback.
pub fn compute_fingerprint(secret_key: &[u8], call_data: &str, prev_fingerprint: &str) -> String {
    let previous = if prev_fingerprint.is_empty() {
        "GENESIS"
    } else {
        prev_fingerprint
    };
    let payload = format!("{call_data}:{previous}");
    let mut mac =
        HmacSha256::new_from_slice(secret_key).expect("HMAC accepts arbitrary key length");
    mac.update(payload.as_bytes());
    let digest = mac.finalize().into_bytes();
    let mut result = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use std::fmt::Write;
        write!(&mut result, "{byte:02x}").expect("writing to String cannot fail");
    }
    result.truncate(FINGERPRINT_HEX_LENGTH);
    result
}

/// Verify an explicit root-first chain without reading runtime state.
pub fn verify_fingerprint_chain(
    secret_key: &[u8],
    links: &[FingerprintLink],
) -> VerificationResult {
    let mut previous = String::new();
    let mut valid = true;
    let mut steps = Vec::with_capacity(links.len());
    for link in links {
        let call_data = normalize_call_data(
            &link.tool_name,
            &link.agent_id,
            link.ring,
            &link.call_id,
            &link.parent_id,
            link.depth,
        );
        let expected = compute_fingerprint(secret_key, &call_data, &previous);
        let fingerprint_match = expected == link.fingerprint;
        valid &= fingerprint_match;
        steps.push(VerificationStep {
            call_id: link.call_id.clone(),
            tool: link.tool_name.clone(),
            depth: link.depth,
            fingerprint_match,
        });
        previous = link.fingerprint.clone();
    }
    VerificationResult {
        valid,
        depth: links.len(),
        steps,
    }
}
