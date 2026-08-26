//! Independent identity UID value tests for the Rust kernel.

use l1_kernel_rs::identity_uid::IdentityUidIssuer;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct UidVector {
    prefix: String,
    body_length: usize,
    max_attempts: usize,
    cases: Vec<IssueCase>,
    verify: Vec<VerifyCase>,
}

#[derive(Debug, Deserialize)]
struct IssueCase {
    tracked: Vec<String>,
    candidates: Vec<String>,
    expected: String,
}

#[derive(Debug, Deserialize)]
struct VerifyCase {
    uid: String,
    expected: bool,
}

#[test]
fn duplicate_candidates_are_bounded_and_resettable() {
    let issuer = IdentityUidIssuer::new("id-", 4, 2);
    assert_eq!(issuer.issue_from_candidates(["abcd", "abcd"]), "id-abcd");
    assert_eq!(issuer.issue_from_candidates(["abcd", "abcd"]), "");
    issuer.reset();
    assert_eq!(issuer.issue_from_candidates(["abcd"]), "id-abcd");
}

#[test]
fn shared_uid_vectors_match_python_reference() {
    let vector: UidVector = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/kernel_identity_uid_vectors.json"
    ))
    .expect("identity UID fixture must be valid JSON");
    for case in vector.cases {
        let issuer =
            IdentityUidIssuer::new(&vector.prefix, vector.body_length, vector.max_attempts);
        for tracked in case.tracked {
            issuer.track_existing(&tracked);
        }
        assert_eq!(issuer.issue_from_candidates(case.candidates), case.expected);
    }
    let issuer = IdentityUidIssuer::new(&vector.prefix, vector.body_length, vector.max_attempts);
    for case in vector.verify {
        assert_eq!(issuer.verify(&case.uid), case.expected);
    }
}
