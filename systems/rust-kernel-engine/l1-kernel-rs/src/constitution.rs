//! Rust candidate for the pure Constitution rule/value/evaluation layer.

use std::collections::BTreeSet;
use std::sync::{Mutex, PoisonError};

use serde::{Deserialize, Serialize};

use crate::gatechain::path_within;

/// Default sandbox directory name used by the Python parameter layer.
pub const CONSTITUTION_SANDBOX_DIR: &str = "praxis-sandbox";
/// Default constitution filename suffix.
pub const CONSTITUTION_FILE_EXT: &str = ".praxis-rules.md";
/// Action length separating one-line actions from multi-step gate actions.
pub const CONSTITUTION_ACTION_LEN_THRESHOLD: usize = 5;
/// Reserved scout identity.
pub const CONSTITUTION_SCOUT_AGENT: &str = "scout";
/// Target keyword that marks shared territory.
pub const CONSTITUTION_SHARED_KEYWORD: &str = "shared";
/// Target keyword that identifies the constitution itself.
pub const CONSTITUTION_KEYWORD: &str = "constitution";

/// Stable rule severity mirrored from Python `RuleSeverity`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum RuleSeverity {
    /// Mandatory rule; a violation blocks where the rule defines blocking.
    Must,
    /// Advisory rule; a violation warns.
    Should,
    /// Optional rule; currently descriptive and non-blocking.
    May,
}

impl RuleSeverity {
    /// Return the stable wire spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Must => "MUST",
            Self::Should => "SHOULD",
            Self::May => "MAY",
        }
    }
}

/// Stable result of one Constitution rule evaluation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum CheckResult {
    /// The rule does not object to the input.
    Pass,
    /// The input may continue with an advisory violation.
    Warn,
    /// The input is constitutionally denied.
    Block,
}

impl CheckResult {
    /// Return the stable wire spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pass => "PASS",
            Self::Warn => "WARN",
            Self::Block => "BLOCK",
        }
    }

    /// Return whether the result permits the action to continue.
    pub const fn allowed(self) -> bool {
        !matches!(self, Self::Block)
    }
}

/// Rule evaluator kind. Custom descriptors use `Noop` and remain data-only.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuleKind {
    /// Check target containment for file actions.
    Territory,
    /// Check target containment for modifying actions.
    Sandbox,
    /// Protect the constitution file and constitution targets.
    ConstitutionModification,
    /// Mark high-risk or long modifying actions for GateChain review.
    Gatechain,
    /// Enforce scout read-only restrictions.
    Scout,
    /// Enforce cross-territory shared-area restrictions.
    CrossTerritory,
    /// Require full-power posture for an explicitly offensive skill input.
    OffensiveSkillPosture,
    /// Descriptive rule with no pure evaluator.
    Noop,
}

/// Action category used by the pre-evaluation index.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
enum ActionCategory {
    File,
    Modify,
    Tool,
    Memory,
    Scout,
    Skill,
}

/// Immutable rule descriptor crossing the language boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConstitutionRule {
    /// Unique machine-readable rule id.
    /// Unique rule id.
    pub id: String,
    /// Constitution section label.
    /// Constitution section grouping.
    /// Section being summarized.
    pub section: String,
    /// Enforcement severity.
    /// MUST / SHOULD / MAY severity.
    pub severity: RuleSeverity,
    /// Human-readable description.
    /// Human-facing rule text.
    pub description: String,
    /// Built-in evaluator kind.
    /// Action-classification kind index.
    pub kind: RuleKind,
    /// Source label (`builtin` or `custom`).
    #[serde(default = "default_source")]
    /// `builtin` or `custom` provenance.
    pub source: String,
    /// Stable classification tags for API/export consumers.
    #[serde(default)]
    /// Sorted matching tags.
    pub tags: Vec<String>,
}

impl ConstitutionRule {
    /// Construct a data-only custom rule that always passes this layer.
    pub fn custom(
        id: impl Into<String>,
        section: impl Into<String>,
        severity: RuleSeverity,
        description: impl Into<String>,
    ) -> Self {
        Self {
            id: id.into(),
            section: section.into(),
            severity,
            description: description.into(),
            kind: RuleKind::Noop,
            source: "custom".to_owned(),
            tags: Vec::new(),
        }
    }

    /// Validate and normalize a rule before it crosses the Rust policy seam.
    ///
    /// # Errors
    ///
    /// `Err` with a stable message for empty id/section, non-builtin
    /// source misuse, custom rules not using the noop kind, or empty tags.
    pub fn validate_and_normalize(mut self) -> Result<Self, &'static str> {
        if self.id.trim().is_empty() {
            return Err("constitution rule id must not be empty");
        }
        if self.section.trim().is_empty() {
            return Err("constitution rule section must not be empty");
        }
        if self.source != "builtin" && self.source != "custom" {
            return Err("constitution rule source must be builtin or custom");
        }
        if self.source == "custom" && self.kind != RuleKind::Noop {
            return Err("custom constitution rules must use the noop kind");
        }
        if self.tags.iter().any(|tag| tag.trim().is_empty()) {
            return Err("constitution rule tags must not be empty");
        }
        self.tags.sort_unstable();
        self.tags.dedup();
        Ok(self)
    }
}

/// Action snapshot consumed by the pure Constitution evaluator.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConstitutionInput {
    /// Action or tool name.
    /// Action under adjudication.
    pub action: String,
    /// Calling agent identity.
    /// Acting agent identity.
    pub agent_id: String,
    /// Target path/resource, if present.
    #[serde(default)]
    /// Target resource/path.
    pub target: String,
    /// Territory roots supplied by the card/adapter.
    #[serde(default)]
    /// Declared territory scopes.
    pub territory: Vec<String>,
    /// Whether the target skill is explicitly offensive-posture.
    #[serde(default)]
    /// Offensive-skill posture input.
    pub offensive_skill: bool,
    /// Explicit posture result supplied by an adapter.
    #[serde(default)]
    /// Full-power posture input.
    pub full_power: bool,
}

impl ConstitutionInput {
    /// Construct a minimal action snapshot.
    pub fn new(action: impl Into<String>, agent_id: impl Into<String>) -> Self {
        Self {
            action: action.into(),
            agent_id: agent_id.into(),
            target: String::new(),
            territory: Vec::new(),
            offensive_skill: false,
            full_power: false,
        }
    }
}

/// One non-pass rule report, matching Python `CheckReport` semantics.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckReport {
    /// Rule that produced the result.
    /// Rule that produced this detail.
    pub rule: ConstitutionRule,
    /// Rule result.
    /// Per-rule verdict.
    pub result: CheckResult,
    /// Stable contextual detail.
    #[serde(default)]
    /// Explanation captured at check time.
    pub detail: String,
}

/// Aggregate decision returned by `ConstitutionEngine::is_allowed`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConstitutionDecision {
    /// Whether no rule blocked the action.
    /// Final allow/deny verdict.
    pub allowed: bool,
    /// Lowercase compatibility spelling used by Python API responses.
    /// Decision summary string.
    pub decision: String,
    /// Number of blocking reports.
    /// Blocking rule count.
    pub blocks: usize,
    /// Number of warning reports.
    /// Warning rule count.
    pub warns: usize,
    /// Non-pass details in evaluation order.
    /// Root-first decision details.
    pub details: Vec<DecisionDetail>,
}

/// Compact decision detail for API/TS consumers.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionDetail {
    /// Rule section.
    pub section: String,
    /// Rule id.
    pub rule_id: String,
    /// Stable result spelling.
    pub result: CheckResult,
    /// Context detail.
    #[serde(default)]
    pub detail: String,
}

/// Configuration values supplied by the deployment/config adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConstitutionPolicy {
    /// Read/search action names.
    pub file_actions: BTreeSet<String>,
    /// Modifying/destructive action names.
    pub modify_actions: BTreeSet<String>,
    /// Actions that must be marked for GateChain review.
    pub gate_actions: BTreeSet<String>,
    /// Actions forbidden to the scout principal.
    pub scout_blocked: BTreeSet<String>,
    /// Sandbox root path.
    pub sandbox_root: String,
    /// Filename extension of the constitution document.
    pub constitution_file_ext: String,
    /// Keyword identifying constitution targets.
    pub constitution_keyword: String,
    /// Action length warning threshold.
    pub action_len_threshold: usize,
    /// Reserved scout principal name.
    pub scout_agent_name: String,
    /// Shared-territory keyword.
    pub shared_keyword: String,
}

impl Default for ConstitutionPolicy {
    fn default() -> Self {
        Self {
            file_actions: set([
                "read",
                "read_file",
                "grep",
                "grep_search",
                "list",
                "list_dir",
                "search",
                "find",
                "stat",
            ]),
            modify_actions: set([
                "write",
                "write_file",
                "edit",
                "replace",
                "replace_string",
                "delete",
                "rename",
                "create",
                "create_file",
                "format",
                "run",
                "run_in_terminal",
            ]),
            gate_actions: set([
                "run_in_terminal",
                "deploy",
                "db_migrate",
                "user_delete",
                "delete_user",
                "destroy",
            ]),
            scout_blocked: set([
                "write",
                "write_file",
                "edit",
                "replace",
                "replace_string",
                "delete",
                "rename",
                "create",
                "create_file",
                "format",
            ]),
            sandbox_root: std::env::temp_dir()
                .join(CONSTITUTION_SANDBOX_DIR)
                .to_string_lossy()
                .into_owned(),
            constitution_file_ext: CONSTITUTION_FILE_EXT.to_owned(),
            constitution_keyword: CONSTITUTION_KEYWORD.to_owned(),
            action_len_threshold: CONSTITUTION_ACTION_LEN_THRESHOLD,
            scout_agent_name: CONSTITUTION_SCOUT_AGENT.to_owned(),
            shared_keyword: CONSTITUTION_SHARED_KEYWORD.to_owned(),
        }
    }
}

/// Thread-safe pure rule evaluator. IO and side effects are adapter-owned.
pub struct ConstitutionEngine {
    policy: ConstitutionPolicy,
    rules: Mutex<Vec<ConstitutionRule>>,
}

impl ConstitutionEngine {
    /// Create the default built-in rule set.
    pub fn new() -> Self {
        Self::with_policy(ConstitutionPolicy::default())
    }

    /// Create an evaluator with explicit policy data.
    pub fn with_policy(policy: ConstitutionPolicy) -> Self {
        Self {
            policy,
            rules: Mutex::new(builtin_rules()),
        }
    }

    /// Return a snapshot of all current rules.
    pub fn rules(&self) -> Vec<ConstitutionRule> {
        self.lock_rules().clone()
    }

    /// Replace all rules, preserving the old snapshot when validation fails.
    pub fn replace_rules(&self, rules: Vec<ConstitutionRule>) {
        let _ = self.replace_rules_checked(rules);
    }

    /// Validate, normalize, and replace rules from an explicit config snapshot.
    ///
    /// # Errors
    ///
    /// Constitution error when any incoming rule fails validation; failure replaces nothing (old snapshot retained).
    pub fn replace_rules_checked(&self, rules: Vec<ConstitutionRule>) -> Result<(), &'static str> {
        let mut normalized = Vec::with_capacity(rules.len());
        let mut ids = BTreeSet::new();
        for rule in rules {
            let rule = rule.validate_and_normalize()?;
            if !ids.insert(rule.id.clone()) {
                return Err("constitution rule id must be unique");
            }
            normalized.push(rule);
        }
        *self.lock_rules() = normalized;
        Ok(())
    }

    /// Evaluate relevant rules and return only non-pass reports.
    pub fn check(&self, input: &ConstitutionInput) -> Vec<CheckReport> {
        let rules = self.lock_rules().clone();
        let relevant = relevant_rules(&rules, &input.action);
        relevant
            .into_iter()
            .filter_map(|rule| {
                let result = self.evaluate_rule(&rule, input);
                if result == CheckResult::Pass {
                    None
                } else {
                    let detail = describe(&rule, input);
                    Some(CheckReport {
                        rule,
                        result,
                        detail,
                    })
                }
            })
            .collect()
    }

    /// Return the Python-compatible aggregate decision shape.
    pub fn is_allowed(&self, input: &ConstitutionInput) -> ConstitutionDecision {
        let reports = self.check(input);
        let blocks = reports
            .iter()
            .filter(|report| report.result == CheckResult::Block)
            .count();
        let warns = reports
            .iter()
            .filter(|report| report.result == CheckResult::Warn)
            .count();
        let allowed = blocks == 0;
        let details = reports
            .iter()
            .map(|report| DecisionDetail {
                section: report.rule.section.clone(),
                rule_id: report.rule.id.clone(),
                result: report.result,
                detail: report.detail.clone(),
            })
            .collect();
        ConstitutionDecision {
            allowed,
            decision: if allowed { "pass" } else { "block" }.to_owned(),
            blocks,
            warns,
            details,
        }
    }

    fn evaluate_rule(&self, rule: &ConstitutionRule, input: &ConstitutionInput) -> CheckResult {
        match rule.kind {
            RuleKind::Territory => {
                if !self.policy.file_actions.contains(&input.action) || input.target.is_empty() {
                    CheckResult::Pass
                } else if !input.territory.is_empty()
                    && !path_within(&input.target, &input.territory)
                {
                    if rule.severity == RuleSeverity::Must {
                        CheckResult::Block
                    } else {
                        CheckResult::Warn
                    }
                } else {
                    CheckResult::Pass
                }
            }
            RuleKind::Sandbox => {
                if !self.policy.modify_actions.contains(&input.action) {
                    CheckResult::Pass
                } else if rule.severity == RuleSeverity::Must
                    && !input.target.is_empty()
                    && !path_within(
                        &input.target,
                        std::slice::from_ref(&self.policy.sandbox_root),
                    )
                {
                    CheckResult::Warn
                } else {
                    CheckResult::Pass
                }
            }
            RuleKind::ConstitutionModification => {
                if input.target.is_empty() {
                    CheckResult::Pass
                } else if input
                    .target
                    .to_lowercase()
                    .contains(&self.policy.constitution_keyword)
                    || input.target.ends_with(&self.policy.constitution_file_ext)
                {
                    CheckResult::Block
                } else {
                    CheckResult::Pass
                }
            }
            RuleKind::Gatechain => {
                if self.policy.gate_actions.contains(&input.action)
                    || (self.policy.modify_actions.contains(&input.action)
                        && input.action.chars().count() > self.policy.action_len_threshold)
                {
                    CheckResult::Warn
                } else {
                    CheckResult::Pass
                }
            }
            RuleKind::Scout => {
                if input.agent_id == self.policy.scout_agent_name
                    && self.policy.scout_blocked.contains(&input.action)
                {
                    CheckResult::Block
                } else {
                    CheckResult::Pass
                }
            }
            RuleKind::CrossTerritory => {
                if self.policy.scout_blocked.contains(&input.action) {
                    if input
                        .territory
                        .iter()
                        .any(|root| root.to_lowercase().contains(&self.policy.shared_keyword))
                    {
                        CheckResult::Block
                    } else {
                        CheckResult::Warn
                    }
                } else {
                    CheckResult::Pass
                }
            }
            RuleKind::OffensiveSkillPosture => {
                if matches!(input.action.as_str(), "skill.use" | "use_skill")
                    && input.offensive_skill
                    && !input.full_power
                {
                    CheckResult::Block
                } else {
                    CheckResult::Pass
                }
            }
            RuleKind::Noop => CheckResult::Pass,
        }
    }

    fn lock_rules(&self) -> std::sync::MutexGuard<'_, Vec<ConstitutionRule>> {
        self.rules.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for ConstitutionEngine {
    fn default() -> Self {
        Self::new()
    }
}

fn builtin_rules() -> Vec<ConstitutionRule> {
    vec![
        rule(
            "territory.write",
            "§2.3",
            RuleSeverity::Must,
            "Agent must not write outside its territory",
            RuleKind::Territory,
            ["territory", "write"],
        ),
        rule(
            "territory.read_l3",
            "§3.1",
            RuleSeverity::Must,
            "Agent must not read files outside its territory without L3 approval",
            RuleKind::Territory,
            ["territory", "read"],
        ),
        rule(
            "gatechain.all",
            "§3.3",
            RuleSeverity::Must,
            "All tool calls must pass GateChain G1-G5",
            RuleKind::Gatechain,
            ["gatechain"],
        ),
        rule(
            "gatechain.cross",
            "§3.4",
            RuleSeverity::Must,
            "Cross-unit tool calls require G5 approval",
            RuleKind::Gatechain,
            ["gatechain", "cross"],
        ),
        rule(
            "sandbox.writes",
            "§4.5",
            RuleSeverity::Must,
            "All modifications must go through sandbox (no direct writes)",
            RuleKind::Sandbox,
            ["sandbox"],
        ),
        rule(
            "sandbox.review",
            "§4.6",
            RuleSeverity::Must,
            "All modifications must be reviewable by L3 before flush",
            RuleKind::Sandbox,
            ["sandbox", "review"],
        ),
        rule(
            "constitution.modify",
            "§4.7",
            RuleSeverity::Must,
            "No Agent may modify the constitution itself",
            RuleKind::ConstitutionModification,
            ["constitution"],
        ),
        rule(
            "audit.trail",
            "§5.1",
            RuleSeverity::Must,
            "All tool calls must be logged with audit trail",
            RuleKind::Noop,
            ["audit"],
        ),
        rule(
            "decision.memory",
            "§5.2",
            RuleSeverity::Should,
            "All decisions must be recorded in memory Ring 2",
            RuleKind::Noop,
            ["memory"],
        ),
        rule(
            "territory.cross_review",
            "§6.1",
            RuleSeverity::Must,
            "Cross-territory changes require peer review",
            RuleKind::CrossTerritory,
            ["territory", "review"],
        ),
        rule(
            "l3.arbiter",
            "§6.2",
            RuleSeverity::Must,
            "L3 is the final arbiter of all disputes",
            RuleKind::Noop,
            ["l3"],
        ),
        rule(
            "scout.readonly",
            "§7.1",
            RuleSeverity::Must,
            "Scouts are read-only and depth=1",
            RuleKind::Scout,
            ["scout"],
        ),
        rule(
            "scout.log",
            "§7.2",
            RuleSeverity::Should,
            "Scout findings must be logged before disposal",
            RuleKind::Scout,
            ["scout", "audit"],
        ),
        rule(
            "ring.context",
            "§8.1",
            RuleSeverity::Must,
            "Agent context must be built from Ring memory, not raw output",
            RuleKind::Noop,
            ["memory", "ring"],
        ),
        rule(
            "ring.persist",
            "§8.2",
            RuleSeverity::Should,
            "Important decisions must be persisted to Ring 3 (long-term)",
            RuleKind::Noop,
            ["memory", "ring"],
        ),
        rule(
            "skill.builtin_readonly",
            "§9.1",
            RuleSeverity::Must,
            "Built-in (shipped) skills are read-only",
            RuleKind::Noop,
            ["skill"],
        ),
        rule(
            "skill.offensive_posture",
            "§9.2",
            RuleSeverity::Must,
            "Offensive-posture skills require attack posture (full_power) for use",
            RuleKind::OffensiveSkillPosture,
            ["skill"],
        ),
    ]
}

fn rule<const N: usize>(
    id: &str,
    section: &str,
    severity: RuleSeverity,
    description: &str,
    kind: RuleKind,
    tags: [&str; N],
) -> ConstitutionRule {
    ConstitutionRule {
        id: id.to_owned(),
        section: section.to_owned(),
        severity,
        description: description.to_owned(),
        kind,
        source: "builtin".to_owned(),
        tags: tags.into_iter().map(str::to_owned).collect(),
    }
}

fn relevant_rules(rules: &[ConstitutionRule], action: &str) -> Vec<ConstitutionRule> {
    let category = action_category(action);
    rules
        .iter()
        .filter(|rule| {
            rule.tags.iter().any(|tag| tag == "audit" || tag == "l3")
                || matches!(rule.kind, RuleKind::Noop)
                || rule_applies_to(rule.kind, category)
        })
        .cloned()
        .collect()
}

fn action_category(action: &str) -> ActionCategory {
    if matches!(
        action,
        "read"
            | "read_file"
            | "grep"
            | "grep_search"
            | "glob"
            | "ls"
            | "list"
            | "list_dir"
            | "search"
            | "find"
            | "stat"
    ) {
        ActionCategory::File
    } else if matches!(
        action,
        "write"
            | "write_file"
            | "edit"
            | "replace"
            | "replace_string"
            | "replace_string_in_file"
            | "delete"
            | "delete_file"
            | "create"
            | "create_file"
            | "rename"
            | "move"
            | "patch"
            | "format"
            | "run"
            | "run_in_terminal"
    ) {
        ActionCategory::Modify
    } else if matches!(
        action,
        "memory_read"
            | "memory_write"
            | "memory_search"
            | "memory_query"
            | "memory_store"
            | "memory_recall"
            | "archive"
            | "recall"
    ) {
        ActionCategory::Memory
    } else if matches!(
        action,
        "scout" | "scout_read" | "scout_search" | "investigate"
    ) {
        ActionCategory::Scout
    } else if matches!(
        action,
        "skill.use" | "use_skill" | "skill.load" | "skill_list" | "skill_use" | "skill_load"
    ) {
        ActionCategory::Skill
    } else {
        ActionCategory::Tool
    }
}

fn rule_applies_to(kind: RuleKind, category: ActionCategory) -> bool {
    match kind {
        RuleKind::Territory => category == ActionCategory::File,
        RuleKind::Sandbox | RuleKind::ConstitutionModification => {
            category == ActionCategory::Modify
        }
        RuleKind::Gatechain => true,
        RuleKind::Scout | RuleKind::CrossTerritory => {
            matches!(
                category,
                ActionCategory::File | ActionCategory::Modify | ActionCategory::Scout
            )
        }
        RuleKind::OffensiveSkillPosture => category == ActionCategory::Skill,
        RuleKind::Noop => true,
    }
}

fn describe(rule: &ConstitutionRule, input: &ConstitutionInput) -> String {
    format!(
        "{}: {} (action={}, agent={}, target={})",
        rule.section, rule.description, input.action, input.agent_id, input.target
    )
}

fn default_source() -> String {
    "builtin".to_owned()
}

fn set<const N: usize>(items: [&str; N]) -> BTreeSet<String> {
    items.into_iter().map(str::to_owned).collect()
}
