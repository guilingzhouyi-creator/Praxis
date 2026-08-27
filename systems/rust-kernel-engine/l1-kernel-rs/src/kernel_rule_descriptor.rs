//! Language-neutral Constitution rule descriptor candidate.

use std::collections::{BTreeMap, BTreeSet};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Rule severity carried by a descriptor.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RuleSeverity {
    /// Mandatory rule.
    Must,
    /// Advisory rule.
    Should,
    /// Informational rule.
    #[default]
    May,
}

/// Result emitted by a rule checker.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum CheckResult {
    /// The rule is satisfied.
    #[default]
    Pass,
    /// The rule is advisory-only for this action.
    Warn,
    /// The rule denies this action.
    Block,
}

/// Convert a Python-compatible severity name, defaulting unknown values to MAY.
pub fn str_to_severity(value: &str) -> RuleSeverity {
    match value {
        "MUST" => RuleSeverity::Must,
        "SHOULD" => RuleSeverity::Should,
        "MAY" => RuleSeverity::May,
        _ => RuleSeverity::May,
    }
}

/// Callback context supplied to an optional rule checker.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuleContext<'a> {
    /// Action name being evaluated.
    pub action: &'a str,
    /// Agent identity supplied by the caller.
    pub agent_id: &'a str,
    /// Target supplied by the caller.
    pub target: &'a str,
    /// Explicit territory values supplied by the caller.
    pub territory: &'a [String],
}

/// Checker callback; provider policy can inject it without crossing the value boundary.
pub type CheckFn =
    Arc<dyn Fn(&RuleDescriptor, RuleContext<'_>) -> Option<CheckResult> + Send + Sync>;

/// Immutable rule identity, metadata, and optional evaluation callback.
pub struct RuleDescriptor {
    /// Unique machine-readable rule identifier.
    pub id: String,
    /// Constitution section containing the rule.
    pub section: String,
    /// Rule severity.
    pub severity: RuleSeverity,
    /// Human-readable rule description.
    pub description: String,
    /// Optional injected checker; absent means PASS.
    pub check_fn: Option<CheckFn>,
    /// Origin marker, normally `builtin` or `custom`.
    pub source: String,
    /// Classification tags kept in deterministic order.
    pub tags: BTreeSet<String>,
    /// Caller-supplied creation timestamp.
    pub created_at: f64,
}

impl std::fmt::Debug for RuleDescriptor {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("RuleDescriptor")
            .field("id", &self.id)
            .field("section", &self.section)
            .field("severity", &self.severity)
            .field("description", &self.description)
            .field("source", &self.source)
            .field("tags", &self.tags)
            .field("created_at", &self.created_at)
            .finish_non_exhaustive()
    }
}

impl RuleDescriptor {
    /// Create a descriptor with no checker and builtin source metadata.
    pub fn new(
        id: impl Into<String>,
        section: impl Into<String>,
        severity: RuleSeverity,
        description: impl Into<String>,
        created_at: f64,
    ) -> Self {
        Self {
            id: id.into(),
            section: section.into(),
            severity,
            description: description.into(),
            check_fn: None,
            source: "builtin".to_owned(),
            tags: BTreeSet::new(),
            created_at,
        }
    }

    /// Attach a checker callback while retaining the descriptor value fields.
    pub fn with_checker(mut self, checker: CheckFn) -> Self {
        self.check_fn = Some(checker);
        self
    }

    /// Set the source marker.
    pub fn with_source(mut self, source: impl Into<String>) -> Self {
        self.source = source.into();
        self
    }

    /// Replace the descriptor tags.
    pub fn with_tags<I, S>(mut self, tags: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        self.tags = tags.into_iter().map(Into::into).collect();
        self
    }

    /// Evaluate the optional checker, defaulting to PASS.
    ///
    /// A checker panic is contained and treated as BLOCK so an adapter
    /// failure cannot cross the policy boundary as an implicit allow.
    pub fn evaluate(
        &self,
        action: &str,
        agent_id: &str,
        target: &str,
        territory: &[String],
    ) -> CheckResult {
        let Some(checker) = self.check_fn.as_ref() else {
            return CheckResult::Pass;
        };
        catch_unwind(AssertUnwindSafe(|| {
            checker(
                self,
                RuleContext {
                    action,
                    agent_id,
                    target,
                    territory,
                },
            )
        }))
        .ok()
        .flatten()
        .unwrap_or(CheckResult::Block)
    }

    /// Serialize descriptor metadata without the callback or timestamp.
    pub fn to_value(&self) -> Value {
        let mut value = BTreeMap::new();
        value.insert("id".to_owned(), Value::String(self.id.clone()));
        value.insert("section".to_owned(), Value::String(self.section.clone()));
        value.insert(
            "severity".to_owned(),
            Value::String(
                serde_json::to_string(&self.severity)
                    .expect("severity serializes")
                    .trim_matches('"')
                    .to_owned(),
            ),
        );
        value.insert(
            "description".to_owned(),
            Value::String(self.description.clone()),
        );
        value.insert("source".to_owned(), Value::String(self.source.clone()));
        value.insert(
            "tags".to_owned(),
            Value::Array(self.tags.iter().cloned().map(Value::String).collect()),
        );
        Value::Object(value.into_iter().collect())
    }
}
