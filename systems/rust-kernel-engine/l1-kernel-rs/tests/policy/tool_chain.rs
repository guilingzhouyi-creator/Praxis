//! Independent tool-call fingerprint-chain tests for the Rust kernel.

use l1_kernel_rs::tool_chain::{
    FingerprintLink, compute_fingerprint, normalize_call_data, verify_fingerprint_chain,
};

#[test]
fn genesis_and_chain_are_deterministic() {
    let key = b"test-key";
    let data = normalize_call_data("tool", "agent", 1, "call-1", "", 1);
    let root = compute_fingerprint(key, &data, "");
    let links = vec![FingerprintLink {
        call_id: "call-1".to_owned(),
        tool_name: "tool".to_owned(),
        agent_id: "agent".to_owned(),
        ring: 1,
        parent_id: String::new(),
        depth: 1,
        fingerprint: root,
    }];
    assert!(verify_fingerprint_chain(key, &links).valid);
}

#[test]
fn tampering_invalidates_only_the_checked_chain() {
    let key = b"test-key";
    let root_data = normalize_call_data("root", "agent", 1, "root", "", 1);
    let root_fp = compute_fingerprint(key, &root_data, "");
    let child_data = normalize_call_data("child", "agent", 1, "child", "root", 2);
    let child_fp = compute_fingerprint(key, &child_data, &root_fp);
    let mut links = vec![
        FingerprintLink {
            call_id: "root".to_owned(),
            tool_name: "root".to_owned(),
            agent_id: "agent".to_owned(),
            ring: 1,
            parent_id: String::new(),
            depth: 1,
            fingerprint: root_fp,
        },
        FingerprintLink {
            call_id: "child".to_owned(),
            tool_name: "child".to_owned(),
            agent_id: "agent".to_owned(),
            ring: 1,
            parent_id: "root".to_owned(),
            depth: 2,
            fingerprint: child_fp,
        },
    ];
    assert!(verify_fingerprint_chain(key, &links).valid);
    links[1].fingerprint.push('x');
    assert!(!verify_fingerprint_chain(key, &links).valid);
}
