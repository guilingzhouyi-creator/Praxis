//! Entropy-injected identity UID issuer candidate for the L1 kernel.
//!
//! Python remains the identity and persistence authority. This module freezes
//! only the prefix, bounded body, collision set, retry budget, and validation
//! values needed by a future adapter.

use std::collections::BTreeSet;
use std::sync::{Mutex, MutexGuard, PoisonError};

/// Default readable UID namespace.
pub const DEFAULT_PREFIX: &str = "id-";
/// Default UID body length in characters.
pub const DEFAULT_BODY_LENGTH: usize = 16;
/// Maximum candidates consumed by one issuance attempt.
pub const DEFAULT_MAX_ATTEMPTS: usize = 8;

/// Thread-safe UID issuer whose entropy source is supplied by the caller.
pub struct IdentityUidIssuer {
    prefix: String,
    body_length: usize,
    max_attempts: usize,
    seen: Mutex<BTreeSet<String>>,
}

impl IdentityUidIssuer {
    /// Create an issuer with explicit value-contract settings.
    pub fn new(prefix: impl Into<String>, body_length: usize, max_attempts: usize) -> Self {
        Self {
            prefix: prefix.into(),
            body_length,
            max_attempts,
            seen: Mutex::new(BTreeSet::new()),
        }
    }

    /// Create an issuer with the Python deployment defaults.
    pub fn with_defaults() -> Self {
        Self::new(DEFAULT_PREFIX, DEFAULT_BODY_LENGTH, DEFAULT_MAX_ATTEMPTS)
    }

    /// Issue from explicit entropy candidates, bounded by the retry budget.
    pub fn issue_from_candidates<I, S>(&self, candidates: I) -> String
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        for candidate in candidates.into_iter().take(self.max_attempts) {
            let body: String = candidate.as_ref().chars().take(self.body_length).collect();
            if body.chars().count() != self.body_length {
                continue;
            }
            let uid = format!("{}{}", self.prefix, body);
            let mut seen = self.lock_seen();
            if seen.insert(uid.clone()) {
                return uid;
            }
        }
        String::new()
    }

    /// Return whether a UID matches the prefix and exact body length.
    pub fn verify(&self, uid: &str) -> bool {
        if uid.is_empty() || !uid.starts_with(&self.prefix) {
            return false;
        }
        uid.strip_prefix(&self.prefix)
            .is_some_and(|body| body.chars().count() == self.body_length)
    }

    /// Track an already-persisted UID so it cannot be reissued.
    pub fn track_existing(&self, uid: &str) {
        if !uid.is_empty() {
            self.lock_seen().insert(uid.to_owned());
        }
    }

    /// Clear the seen set for lifecycle/test reset.
    pub fn reset(&self) {
        self.lock_seen().clear();
    }

    fn lock_seen(&self) -> MutexGuard<'_, BTreeSet<String>> {
        self.seen.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for IdentityUidIssuer {
    fn default() -> Self {
        Self::with_defaults()
    }
}

#[cfg(test)]
mod tests {
    use super::IdentityUidIssuer;
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
            "../../../tests/fixtures/kernel_identity_uid_vectors.json"
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
        let issuer =
            IdentityUidIssuer::new(&vector.prefix, vector.body_length, vector.max_attempts);
        for case in vector.verify {
            assert_eq!(issuer.verify(&case.uid), case.expected);
        }
    }
}
