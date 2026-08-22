//! Rust-native reputation ledger candidate for explicit GateChain inputs.

use std::collections::BTreeMap;
use std::sync::{PoisonError, RwLock};

/// Default score used when an identity has no ledger entry.
pub const DEFAULT_REPUTATION: f64 = 0.85;
/// Lowest score accepted by the ledger.
pub const MIN_REPUTATION: f64 = 0.0;
/// Highest score accepted by the ledger.
pub const MAX_REPUTATION: f64 = 1.0;
/// Delta for a successful task.
pub const TASK_SUCCESS_DELTA: f64 = 0.02;
/// Delta for a failed task.
pub const TASK_FAILURE_DELTA: f64 = -0.05;
/// Delta for an approved review.
pub const REVIEW_APPROVED_DELTA: f64 = 0.01;
/// Delta for a rejected review.
pub const REVIEW_REJECTED_DELTA: f64 = -0.03;
/// Delta for an upheld dispute.
pub const DISPUTE_UPHELD_DELTA: f64 = 0.03;
/// Delta for a dismissed dispute.
pub const DISPUTE_DISMISSED_DELTA: f64 = -0.02;

/// Explicit score policy supplied by the kernel owner.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ReputationPolicy {
    /// Score returned for an identity not present in the ledger.
    pub default_score: f64,
    /// Inclusive lower clamp bound.
    pub min_score: f64,
    /// Inclusive upper clamp bound.
    pub max_score: f64,
    /// Task success adjustment.
    pub task_success_delta: f64,
    /// Task failure adjustment.
    pub task_failure_delta: f64,
    /// Review approval adjustment.
    pub review_approved_delta: f64,
    /// Review rejection adjustment.
    pub review_rejected_delta: f64,
    /// Upheld dispute adjustment.
    pub dispute_upheld_delta: f64,
    /// Dismissed dispute adjustment.
    pub dispute_dismissed_delta: f64,
}

impl Default for ReputationPolicy {
    fn default() -> Self {
        Self {
            default_score: DEFAULT_REPUTATION,
            min_score: MIN_REPUTATION,
            max_score: MAX_REPUTATION,
            task_success_delta: TASK_SUCCESS_DELTA,
            task_failure_delta: TASK_FAILURE_DELTA,
            review_approved_delta: REVIEW_APPROVED_DELTA,
            review_rejected_delta: REVIEW_REJECTED_DELTA,
            dispute_upheld_delta: DISPUTE_UPHELD_DELTA,
            dispute_dismissed_delta: DISPUTE_DISMISSED_DELTA,
        }
    }
}

impl ReputationPolicy {
    /// Validate bounds and deltas before a ledger can use the policy.
    pub fn validate(self) -> Result<(), &'static str> {
        let bounds = [self.default_score, self.min_score, self.max_score];
        if bounds.iter().any(|value| !value.is_finite()) {
            return Err("reputation bounds must be finite");
        }
        if self.min_score > self.max_score
            || self.default_score < self.min_score
            || self.default_score > self.max_score
        {
            return Err("reputation bounds are inconsistent");
        }
        let deltas = [
            self.task_success_delta,
            self.task_failure_delta,
            self.review_approved_delta,
            self.review_rejected_delta,
            self.dispute_upheld_delta,
            self.dispute_dismissed_delta,
        ];
        if deltas.iter().any(|value| !value.is_finite()) {
            return Err("reputation deltas must be finite");
        }
        Ok(())
    }
}

/// Thread-safe bounded score store; provider, persistence, and GateChain stay outside.
pub struct ReputationLedger {
    policy: ReputationPolicy,
    scores: RwLock<BTreeMap<String, f64>>,
}

impl ReputationLedger {
    /// Create an empty ledger after validating its explicit policy.
    pub fn new(policy: ReputationPolicy) -> Result<Self, &'static str> {
        policy.validate()?;
        Ok(Self {
            policy,
            scores: RwLock::new(BTreeMap::new()),
        })
    }

    /// Return the policy used by this ledger.
    pub const fn policy(&self) -> ReputationPolicy {
        self.policy
    }

    /// Return a score or the configured default for an unknown identity.
    pub fn get(&self, agent_id: &str) -> f64 {
        self.scores
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .get(agent_id)
            .copied()
            .unwrap_or(self.policy.default_score)
    }

    /// Set a score after rejecting non-finite input and applying bounds.
    pub fn set(&self, agent_id: impl Into<String>, score: f64) -> Result<f64, &'static str> {
        let normalized = self.normalize(score)?;
        self.scores
            .write()
            .unwrap_or_else(PoisonError::into_inner)
            .insert(agent_id.into(), normalized);
        Ok(normalized)
    }

    /// Apply a finite delta and return the clamped score.
    pub fn adjust(&self, agent_id: impl Into<String>, delta: f64) -> Result<f64, &'static str> {
        if !delta.is_finite() {
            return Err("reputation delta must be finite");
        }
        let agent_id = agent_id.into();
        let mut scores = self.scores.write().unwrap_or_else(PoisonError::into_inner);
        let current = scores
            .get(&agent_id)
            .copied()
            .unwrap_or(self.policy.default_score);
        let next = self.normalize(current + delta)?;
        scores.insert(agent_id, next);
        Ok(next)
    }

    /// Record a task outcome using the configured task delta.
    pub fn record_task(
        &self,
        agent_id: impl Into<String>,
        success: bool,
    ) -> Result<f64, &'static str> {
        self.adjust(
            agent_id,
            if success {
                self.policy.task_success_delta
            } else {
                self.policy.task_failure_delta
            },
        )
    }

    /// Record a cross-review outcome using the configured review delta.
    pub fn record_review(
        &self,
        agent_id: impl Into<String>,
        approved: bool,
    ) -> Result<f64, &'static str> {
        self.adjust(
            agent_id,
            if approved {
                self.policy.review_approved_delta
            } else {
                self.policy.review_rejected_delta
            },
        )
    }

    /// Record a dispute outcome using the configured dispute delta.
    pub fn record_dispute(
        &self,
        agent_id: impl Into<String>,
        upheld: bool,
    ) -> Result<f64, &'static str> {
        self.adjust(
            agent_id,
            if upheld {
                self.policy.dispute_upheld_delta
            } else {
                self.policy.dispute_dismissed_delta
            },
        )
    }

    /// Return a deterministic snapshot without exposing the lock.
    pub fn snapshot(&self) -> BTreeMap<String, f64> {
        self.scores
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    fn normalize(&self, score: f64) -> Result<f64, &'static str> {
        if !score.is_finite() {
            return Err("reputation score must be finite");
        }
        Ok(score.clamp(self.policy.min_score, self.policy.max_score))
    }
}

impl Default for ReputationLedger {
    fn default() -> Self {
        Self::new(ReputationPolicy::default()).expect("default reputation policy is valid")
    }
}
