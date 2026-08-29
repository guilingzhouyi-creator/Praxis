//! Rust-native skill registry and guidance mechanism for the L1 kernel.
//!
//! This module reconstructs the bounded, deterministic part of Python's
//! `SkillManager`: skill metadata, write authorization, Cell bindings, usage
//! accounting, keyword retrieval, progressive disclosure, staged guidance,
//! dependency-DAG validation, and checkpoint values. File discovery,
//! Markdown/YAML parsing, prompt providers, EventBus delivery, memory
//! distillation, and L3 policy orchestration remain explicit host adapters.

use std::collections::{BTreeMap, BTreeSet, HashMap, VecDeque};
use std::fmt::{Display, Formatter};
use std::sync::{Mutex, MutexGuard, PoisonError, RwLock};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};

/// Maximum description characters retained by a skill record.
pub const DEFAULT_DESCRIPTION_LIMIT: usize = 200;
/// Maximum prompt characters retained by the mechanism registry.
pub const DEFAULT_PROMPT_LIMIT: usize = 2_000;
/// Maximum skills retained by one registry.
pub const DEFAULT_MAX_SKILLS: usize = 512;
/// Maximum rules retained by one skill.
pub const DEFAULT_MAX_RULES: usize = 128;
/// Maximum procedures retained by one skill.
pub const DEFAULT_MAX_PROCEDURES: usize = 128;
/// Maximum tags retained by one skill.
pub const DEFAULT_MAX_TAGS: usize = 32;
/// Maximum dependencies retained by one skill.
pub const DEFAULT_MAX_DEPENDENCIES: usize = 64;
/// Maximum staged guidance steps retained by one skill.
pub const DEFAULT_MAX_STAGES: usize = 64;
/// Maximum stage-state entries retained by one registry.
pub const DEFAULT_MAX_STAGE_SESSIONS: usize = 4_096;
/// Maximum full-index rows returned by a list operation.
pub const DEFAULT_FULL_INDEX_LIMIT: usize = 50;
/// Maximum stage-state idle age in caller-supplied seconds.
pub const DEFAULT_STAGE_STATE_TTL: f64 = 3_600.0;
/// Version of the Rust-owned skill checkpoint.
pub const SKILL_DOCUMENT_VERSION: u32 = 1;

/// Skill lifecycle state used by injection and retrieval policy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SkillStatus {
    /// Draft records are never automatically injected.
    Draft,
    /// Canary records require an explicit injection target.
    Canary,
    /// Active records are eligible when all other gates pass.
    Active,
    /// Retired records remain inspectable but are not injectable.
    Retired,
    /// Deprecated records remain inspectable but are not injectable.
    Deprecated,
}

impl Default for SkillStatus {
    /// Use the safe active default used by the Python registry.
    fn default() -> Self {
        Self::Active
    }
}

impl SkillStatus {
    /// Return whether this lifecycle state can be injected automatically.
    pub const fn injectable(self) -> bool {
        matches!(self, Self::Active | Self::Canary)
    }
}

/// Security posture attached to a skill.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SkillPosture {
    /// Normal construction and verification work.
    Productive,
    /// Explicit reverse/attack-testing work.
    Offensive,
}

impl Default for SkillPosture {
    /// Default to the non-offensive posture.
    fn default() -> Self {
        Self::Productive
    }
}

/// Progressive-disclosure mode for a skill.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SkillDisclosure {
    /// Include the full structured content.
    Full,
    /// Include only the catalog/index row.
    Index,
    /// Hide from automatic disclosure.
    None,
}

impl Default for SkillDisclosure {
    /// Include skills in the normal structured view.
    fn default() -> Self {
        Self::Full
    }
}

/// Declarative scope of a skill binding.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SkillScope {
    /// Target one agent identity.
    Agent,
    /// Target one Cell identity.
    Cell,
    /// Global skill with no narrow target.
    Global,
}

impl Default for SkillScope {
    /// Use an unscoped/global default.
    fn default() -> Self {
        Self::Global
    }
}

/// Strength of a skill prerequisite.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DependencyKind {
    /// The dependency is required for correct output.
    Hard,
    /// The dependency improves output but is not required.
    Soft,
}

impl Default for DependencyKind {
    /// Preserve the Python default for legacy records.
    fn default() -> Self {
        Self::Soft
    }
}

/// Operating mode for staged guidance.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum GuidanceMode {
    /// Guidance fields are inert and skills behave as plain records.
    Small,
    /// Stages, prerequisites, and card-linked progression are active.
    Full,
}

impl Default for GuidanceMode {
    /// Use full staged guidance by default.
    fn default() -> Self {
        Self::Full
    }
}

/// Field-level policy for the Rust skill mechanism.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SkillPolicy {
    /// Maximum number of retained skills.
    pub max_skills: usize,
    /// Maximum description character count.
    pub description_limit: usize,
    /// Maximum prompt character count.
    pub prompt_limit: usize,
    /// Maximum rules per skill.
    pub max_rules: usize,
    /// Maximum procedures per skill.
    pub max_procedures: usize,
    /// Maximum tags per skill.
    pub max_tags: usize,
    /// Maximum dependencies per skill.
    pub max_dependencies: usize,
    /// Maximum staged steps per skill.
    pub max_stages: usize,
    /// Maximum retained per-Cell stage sessions.
    pub max_stage_sessions: usize,
    /// Stage-state idle age in caller-supplied seconds.
    pub stage_state_ttl: f64,
    /// Minimum clearance for external structural writes.
    pub write_min_clearance: u8,
    /// Roles allowed to write regardless of numeric clearance.
    pub write_roles: Vec<String>,
    /// Whether the offensive posture gate is enabled.
    pub offensive_enabled: bool,
    /// Card natures allowed to inject offensive skills.
    pub offensive_natures: Vec<String>,
    /// Whether full catalog rows may be returned.
    pub full_index_enabled: bool,
    /// Maximum rows in a full catalog view.
    pub full_index_limit: usize,
    /// Whether strategy/execution audience routing is enabled.
    pub audience_filter_enabled: bool,
    /// Whether strategy callers may view execution capabilities.
    pub strategy_capability_view: bool,
    /// Guidance operating mode.
    pub guidance_mode: GuidanceMode,
    /// Whether task-similarity retrieval is enabled.
    pub retrieval_enabled: bool,
    /// Whether contribution curation is enabled by the host.
    pub curation_enabled: bool,
    /// Minimum useful trials for host curation.
    pub contribution_min_trials: u64,
    /// Minimum useful ratio for host curation.
    pub contribution_min_ratio: f64,
    /// Minimum score accepted by host retrieval.
    pub retrieval_min_score: f64,
}

impl Default for SkillPolicy {
    /// Apply bounded, closed-by-default mechanism limits.
    fn default() -> Self {
        Self {
            max_skills: DEFAULT_MAX_SKILLS,
            description_limit: DEFAULT_DESCRIPTION_LIMIT,
            prompt_limit: DEFAULT_PROMPT_LIMIT,
            max_rules: DEFAULT_MAX_RULES,
            max_procedures: DEFAULT_MAX_PROCEDURES,
            max_tags: DEFAULT_MAX_TAGS,
            max_dependencies: DEFAULT_MAX_DEPENDENCIES,
            max_stages: DEFAULT_MAX_STAGES,
            max_stage_sessions: DEFAULT_MAX_STAGE_SESSIONS,
            stage_state_ttl: DEFAULT_STAGE_STATE_TTL,
            write_min_clearance: 3,
            write_roles: vec![
                "l3".to_owned(),
                "reviewer".to_owned(),
                "deployer".to_owned(),
            ],
            offensive_enabled: true,
            offensive_natures: vec!["security-test".to_owned(), "attack".to_owned()],
            full_index_enabled: false,
            full_index_limit: DEFAULT_FULL_INDEX_LIMIT,
            audience_filter_enabled: true,
            strategy_capability_view: false,
            guidance_mode: GuidanceMode::Full,
            retrieval_enabled: true,
            curation_enabled: true,
            contribution_min_trials: 3,
            contribution_min_ratio: 0.5,
            retrieval_min_score: 0.0,
        }
    }
}

impl SkillPolicy {
    /// Validate capacities, thresholds, and authorization defaults.
    pub fn validate(&self) -> Result<(), SkillError> {
        if self.max_skills == 0
            || self.description_limit == 0
            || self.prompt_limit == 0
            || self.max_rules == 0
            || self.max_procedures == 0
            || self.max_tags == 0
            || self.max_dependencies == 0
            || self.max_stages == 0
            || self.max_stage_sessions == 0
            || self.full_index_limit == 0
        {
            return Err(SkillError::InvalidPolicy(
                "skill capacities must be positive".to_owned(),
            ));
        }
        if !self.stage_state_ttl.is_finite() || self.stage_state_ttl < 0.0 {
            return Err(SkillError::InvalidPolicy(
                "stage_state_ttl must be finite and non-negative".to_owned(),
            ));
        }
        if !self.contribution_min_ratio.is_finite()
            || !(0.0..=1.0).contains(&self.contribution_min_ratio)
            || !self.retrieval_min_score.is_finite()
            || self.retrieval_min_score < 0.0
        {
            return Err(SkillError::InvalidPolicy(
                "skill score thresholds are invalid".to_owned(),
            ));
        }
        if self.write_roles.iter().any(|role| role.trim().is_empty()) {
            return Err(SkillError::InvalidPolicy(
                "write roles must not be blank".to_owned(),
            ));
        }
        if self
            .offensive_natures
            .iter()
            .any(|nature| nature.trim().is_empty())
        {
            return Err(SkillError::InvalidPolicy(
                "offensive natures must not be blank".to_owned(),
            ));
        }
        Ok(())
    }
}

/// Principal supplied by a host at a skill mutation boundary.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SkillPrincipal {
    /// Stable agent identity, when available.
    pub agent_id: String,
    /// Explicit role used for write and audience checks.
    pub role: String,
    /// Caller clearance supplied by the host authority.
    pub clearance: u8,
    /// Trusted boot/internal mutation marker.
    pub internal: bool,
}

impl SkillPrincipal {
    /// Construct an external caller with explicit identity and clearance.
    pub fn external(agent_id: impl Into<String>, role: impl Into<String>, clearance: u8) -> Self {
        Self {
            agent_id: agent_id.into(),
            role: role.into(),
            clearance,
            internal: false,
        }
    }

    /// Construct a trusted internal caller for host-controlled bootstrap.
    pub fn internal() -> Self {
        Self {
            agent_id: String::new(),
            role: "internal".to_owned(),
            clearance: u8::MAX,
            internal: true,
        }
    }

    /// Resolve the effective role from an explicit role or agent prefix.
    pub fn effective_role(&self) -> String {
        if !self.role.trim().is_empty() {
            return self.role.trim().to_owned();
        }
        for prefix in ["agent-", "agent_"] {
            if let Some(role) = self.agent_id.strip_prefix(prefix) {
                return role.to_owned();
            }
        }
        self.agent_id.clone()
    }

    /// Return the stable actor string used in summaries and audit adapters.
    pub fn actor(&self) -> String {
        if !self.agent_id.trim().is_empty() {
            self.agent_id.clone()
        } else {
            self.effective_role()
        }
    }
}

/// One staged guidance instruction.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SkillStage {
    /// Stable stage identifier.
    pub id: String,
    /// Human-readable stage name.
    #[serde(default)]
    pub name: String,
    /// Bounded stage instructions.
    #[serde(default)]
    pub instructions: String,
    /// Host-defined completion marker.
    #[serde(default)]
    pub completion: String,
}

/// One structured skill record owned by the Rust registry.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SkillSpec {
    /// Unique skill identifier.
    pub name: String,
    /// Human-readable description.
    #[serde(default)]
    pub description: String,
    /// Bounded prompt body; providers never execute it here.
    #[serde(default)]
    pub prompt: String,
    /// Declarative rules consumed by a host.
    #[serde(default)]
    pub rules: Vec<String>,
    /// Structured procedures retained at the wire boundary.
    #[serde(default)]
    pub procedures: Vec<Value>,
    /// Opaque host knowledge values.
    #[serde(default)]
    pub knowledge: Map<String, Value>,
    /// Tool allow-list; absent means host policy decides.
    #[serde(default)]
    pub allowed_tools: Option<Vec<String>>,
    /// Prompt variable names.
    #[serde(default)]
    pub variables: Vec<String>,
    /// Audience/domain tags.
    #[serde(default)]
    pub tags: Vec<String>,
    /// Prerequisite skill names.
    #[serde(default)]
    pub dependencies: Vec<String>,
    /// Prerequisite strength.
    #[serde(default)]
    pub dependency_kind: DependencyKind,
    /// Security posture.
    #[serde(default)]
    pub posture: SkillPosture,
    /// Progressive disclosure mode.
    #[serde(default)]
    pub disclosure: SkillDisclosure,
    /// Staged guidance records.
    #[serde(default)]
    pub stages: Vec<SkillStage>,
    /// Forward guidance edges.
    #[serde(default)]
    pub next: Vec<String>,
    /// Explicit user-invocation-only marker.
    #[serde(default)]
    pub disable_model_invocation: bool,
    /// Source label supplied by the host adapter.
    #[serde(default)]
    pub source: String,
    /// Builtin records are immutable to external writers.
    #[serde(default)]
    pub builtin: bool,
    /// Lifecycle status.
    #[serde(default)]
    pub status: SkillStatus,
    /// Generalization layer (`exec`, `decision`, or host-defined).
    #[serde(default)]
    pub layer: String,
    /// Declarative scope.
    #[serde(default)]
    pub scope: SkillScope,
    /// Identity selected by the scope.
    #[serde(default)]
    pub scope_identity: String,
    /// Priority used by host conflict resolution.
    #[serde(default)]
    pub priority: i64,
    /// Host-supplied load timestamp.
    #[serde(default)]
    pub loaded_at: f64,
    /// Host-supplied last-use timestamp.
    #[serde(default)]
    pub last_used: f64,
    /// Total useful completions.
    #[serde(default)]
    pub useful_count: u64,
    /// Total usage count.
    #[serde(default)]
    pub usage_count: u64,
    /// Fine-grained contribution counters.
    #[serde(default)]
    pub usage_by_dimension: BTreeMap<String, u64>,
}

impl SkillSpec {
    /// Construct a minimal active skill.
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: String::new(),
            prompt: String::new(),
            rules: Vec::new(),
            procedures: Vec::new(),
            knowledge: Map::new(),
            allowed_tools: None,
            variables: Vec::new(),
            tags: Vec::new(),
            dependencies: Vec::new(),
            dependency_kind: DependencyKind::Soft,
            posture: SkillPosture::Productive,
            disclosure: SkillDisclosure::Full,
            stages: Vec::new(),
            next: Vec::new(),
            disable_model_invocation: false,
            source: String::new(),
            builtin: false,
            status: SkillStatus::Active,
            layer: String::new(),
            scope: SkillScope::Global,
            scope_identity: String::new(),
            priority: 0,
            loaded_at: 0.0,
            last_used: 0.0,
            useful_count: 0,
            usage_count: 0,
            usage_by_dimension: BTreeMap::new(),
        }
    }

    /// Return the description/prompt-bounded clone used by the registry.
    pub fn bounded(mut self, policy: &SkillPolicy) -> Self {
        self.description = self
            .description
            .chars()
            .take(policy.description_limit)
            .collect();
        self.prompt = self.prompt.chars().take(policy.prompt_limit).collect();
        self.rules.truncate(policy.max_rules);
        self.procedures.truncate(policy.max_procedures);
        self.tags = normalize_strings(std::mem::take(&mut self.tags), policy.max_tags);
        self.variables = normalize_strings(std::mem::take(&mut self.variables), policy.max_tags);
        self.dependencies = normalize_strings(
            std::mem::take(&mut self.dependencies),
            policy.max_dependencies,
        );
        self.next = normalize_strings(std::mem::take(&mut self.next), policy.max_dependencies);
        self.stages.truncate(policy.max_stages);
        for stage in &mut self.stages {
            stage.id = stage.id.trim().to_owned();
            stage.name = stage.name.chars().take(policy.description_limit).collect();
            stage.instructions = stage
                .instructions
                .chars()
                .take(policy.prompt_limit)
                .collect();
            stage.completion = stage
                .completion
                .chars()
                .take(policy.description_limit)
                .collect();
        }
        if self.scope != SkillScope::Global && self.scope_identity.trim().is_empty() {
            self.scope = SkillScope::Global;
        }
        self
    }

    /// Validate identity, lifecycle, and bounded collection invariants.
    pub fn validate(&self, policy: &SkillPolicy) -> Result<(), SkillError> {
        if self.name.trim().is_empty() || self.name.contains('\0') {
            return Err(SkillError::Invalid(
                "skill name must be non-empty and NUL-free".to_owned(),
            ));
        }
        if self.name.chars().count() > policy.description_limit * 2 {
            return Err(SkillError::Invalid(
                "skill name exceeds the bounded identity length".to_owned(),
            ));
        }
        if !self.loaded_at.is_finite() || !self.last_used.is_finite() {
            return Err(SkillError::Invalid(
                "skill timestamps must be finite".to_owned(),
            ));
        }
        if self.rules.len() > policy.max_rules
            || self.procedures.len() > policy.max_procedures
            || self.tags.len() > policy.max_tags
            || self.variables.len() > policy.max_tags
            || self.dependencies.len() > policy.max_dependencies
            || self.next.len() > policy.max_dependencies
            || self.stages.len() > policy.max_stages
        {
            return Err(SkillError::Capacity(
                "skill collection exceeds policy bound".to_owned(),
            ));
        }
        if self.dependencies.iter().any(|name| name == &self.name)
            || self.next.iter().any(|name| name == &self.name)
        {
            return Err(SkillError::Invalid(
                "skill guidance cannot self-reference".to_owned(),
            ));
        }
        if self
            .stages
            .iter()
            .any(|stage| stage.id.trim().is_empty() || stage.id.contains('\0'))
        {
            return Err(SkillError::Invalid(
                "stage ids must be non-empty and NUL-free".to_owned(),
            ));
        }
        if self
            .tags
            .iter()
            .any(|value| value.trim().is_empty() || value.contains('\0'))
        {
            return Err(SkillError::Invalid(
                "skill tags must be non-empty and NUL-free".to_owned(),
            ));
        }
        if self.scope != SkillScope::Global
            && (self.scope_identity.trim().is_empty() || self.scope_identity.contains('\0'))
        {
            return Err(SkillError::Invalid(
                "scoped skills require a non-empty NUL-free identity".to_owned(),
            ));
        }
        Ok(())
    }

    /// Expand `$VARIABLE` placeholders without invoking a provider.
    pub fn expand(&self, variables: &BTreeMap<String, String>) -> String {
        let mut expanded = self.prompt.clone();
        for (key, value) in variables {
            let marker = format!("${}", key.to_ascii_uppercase());
            expanded = expanded.replace(&marker, value);
        }
        expanded
    }
}

/// External contract used to reject unsafe skill content before admission.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SkillContentPolicy {
    /// Case-insensitive substrings that are forbidden in prompt/rules.
    #[serde(default)]
    pub forbidden_patterns: Vec<String>,
    /// Project-specific literals that prevent generalization.
    #[serde(default)]
    pub forbidden_literals: Vec<String>,
}

impl Default for SkillContentPolicy {
    /// Use the minimal fail-closed constitutional checks.
    fn default() -> Self {
        Self {
            forbidden_patterns: vec![
                "bypass sandbox".to_owned(),
                "skip gate".to_owned(),
                "modify constitution".to_owned(),
                "swallow exception".to_owned(),
            ],
            forbidden_literals: vec![
                "systems/python-reference-runtime".to_owned(),
                "systems/rust-kernel-engine".to_owned(),
                "config/skills".to_owned(),
            ],
        }
    }
}

/// One agent/cell/card context used by injection filtering.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct InjectionContext {
    /// Agent identity.
    #[serde(default)]
    pub agent_id: String,
    /// Cell identity.
    #[serde(default)]
    pub cell_id: String,
    /// Resolved role.
    #[serde(default)]
    pub role: String,
    /// Card nature/tag values.
    #[serde(default)]
    pub card_natures: Vec<String>,
    /// Current security posture/nature.
    #[serde(default)]
    pub posture: String,
}

/// Public catalog row for one skill.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SkillSummary {
    /// Skill identifier.
    pub name: String,
    /// Bounded description.
    pub description: String,
    /// Rule count.
    pub rules: usize,
    /// Procedure count.
    pub procedures: usize,
    /// Tags.
    pub tags: Vec<String>,
    /// Prompt only when explicitly requested.
    pub prompt: String,
    /// Source label.
    pub source: String,
    /// Builtin marker.
    pub builtin: bool,
    /// Security posture.
    pub posture: SkillPosture,
    /// Lifecycle status.
    pub status: SkillStatus,
    /// Disclosure mode.
    pub disclosure: SkillDisclosure,
    /// Stage count.
    pub stages: usize,
    /// Forward guidance names.
    pub next: Vec<String>,
    /// Load timestamp.
    pub loaded_at: f64,
    /// Last-use timestamp.
    pub last_used: f64,
    /// User-invocation-only marker.
    pub disable_model_invocation: bool,
    /// Prerequisite names.
    pub dependencies: Vec<String>,
    /// Prerequisite strength.
    pub dependency_kind: DependencyKind,
    /// Generalization layer.
    pub layer: String,
    /// Scope.
    pub scope: SkillScope,
    /// Scope identity.
    pub scope_identity: String,
    /// Host conflict priority.
    pub priority: i64,
}

/// Machine-readable structured projection consumed by an agent host.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StructuredSkill {
    /// Whether the projection succeeded.
    pub success: bool,
    /// Skill identifier.
    pub name: String,
    /// Bounded description.
    pub description: String,
    /// Rules.
    pub rules: Vec<String>,
    /// Procedures.
    pub procedures: Vec<Value>,
    /// Tool allow-list.
    pub allowed_tools: Vec<String>,
    /// Variables.
    pub variables: Vec<String>,
    /// Dependencies.
    pub dependencies: Vec<String>,
    /// Forward guidance.
    pub next: Vec<String>,
    /// Disclosure mode.
    pub disclosure: SkillDisclosure,
    /// Lifecycle status.
    pub status: SkillStatus,
    /// Current stage, if staged.
    pub stage: Option<StageView>,
}

/// Current stage projection for a skill/session pair.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StageView {
    /// Skill name.
    pub skill: String,
    /// Whether this skill has active stages.
    pub staged: bool,
    /// Zero-based active stage index.
    pub stage_index: usize,
    /// Active stage data.
    pub stage: SkillStage,
    /// Next stage id, when present.
    pub next_stage: Option<String>,
    /// Whether this is the final stage.
    pub done: bool,
}

/// Weighted keyword-query result.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SkillSearchResult {
    /// Skill identifier.
    pub name: String,
    /// Weighted score.
    pub score: f64,
    /// Full bounded skill record.
    pub skill: SkillSpec,
}

/// Stable guidance-graph validation result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GuidanceGraphReport {
    /// Whether the graph has no cycles.
    pub acyclic: bool,
    /// Detected cycles.
    pub cycles: Vec<Vec<String>>,
    /// Number of graph nodes.
    pub nodes: usize,
}

/// Registry mutation counters and current revision.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SkillStats {
    /// Current number of skills.
    pub total: usize,
    /// Structural revision.
    pub revision: u64,
    /// Number of registration operations.
    pub registers: u64,
    /// Number of replacements.
    pub replacements: u64,
    /// Number of removals.
    pub deletes: u64,
    /// Number of usage bumps.
    pub usage_bumps: u64,
    /// Number of bound Cell edges.
    pub cell_bindings: usize,
    /// Number of active stage sessions.
    pub stage_sessions: usize,
}

/// Error categories returned by the Rust skill mechanism.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SkillError {
    /// Invalid skill data or query.
    Invalid(String),
    /// Invalid policy.
    InvalidPolicy(String),
    /// Bounded capacity was exceeded.
    Capacity(String),
    /// External caller lacks structural write clearance.
    PermissionDenied(String),
    /// Requested skill does not exist.
    NotFound(String),
    /// Builtin records cannot be structurally changed.
    BuiltinReadOnly(String),
    /// Skill content violates the injected contract.
    ContentViolation(Vec<String>),
    /// Guidance graph contains a cycle.
    GraphCycle(GuidanceGraphReport),
}

impl Display for SkillError {
    /// Render a stable error message for adapters and tests.
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid skill: {message}"),
            Self::InvalidPolicy(message) => write!(formatter, "invalid skill policy: {message}"),
            Self::Capacity(message) => write!(formatter, "skill capacity exceeded: {message}"),
            Self::PermissionDenied(message) => {
                write!(formatter, "skill permission denied: {message}")
            }
            Self::NotFound(name) => write!(formatter, "skill not found: {name}"),
            Self::BuiltinReadOnly(name) => write!(formatter, "builtin skill is read-only: {name}"),
            Self::ContentViolation(violations) => write!(
                formatter,
                "skill content rejected: {}",
                violations.join("; ")
            ),
            Self::GraphCycle(report) => write!(
                formatter,
                "skill guidance graph contains {} cycle(s)",
                report.cycles.len()
            ),
        }
    }
}

impl std::error::Error for SkillError {}

/// Sort key for catalog listing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkillSort {
    /// Lexical name order.
    Name,
    /// Newest loaded first.
    LoadedAt,
    /// Most recently used first.
    LastUsed,
    /// Highest priority first.
    Priority,
}

/// Catalog-list filters.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SkillListFilter {
    /// Any-match tag filter.
    pub tags: Vec<String>,
    /// Optional generalization layer.
    pub layer: String,
    /// Optional maximum rows.
    pub limit: usize,
    /// Include bounded prompt text.
    pub include_prompt: bool,
    /// Caller context for audience routing.
    pub context: InjectionContext,
    /// Whether audience filtering is requested.
    pub apply_audience_filter: bool,
}

/// Versioned checkpoint of the skill registry and binding state.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SkillCheckpoint {
    /// Checkpoint schema version.
    pub document_version: u32,
    /// Structural registry revision.
    pub revision: u64,
    /// Deterministically ordered skills.
    pub skills: Vec<SkillSpec>,
    /// Cell-to-skill edges.
    pub cell_bindings: BTreeMap<String, Vec<String>>,
    /// Per-session stage cursors.
    pub stage_sessions: Vec<StageSessionRecord>,
}

/// One persisted staged-guidance cursor.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StageSessionRecord {
    /// Skill name.
    pub skill: String,
    /// Caller session key.
    pub session_key: String,
    /// Current stage index.
    pub stage_index: usize,
    /// Last touch timestamp supplied by the host.
    pub touched_at: f64,
}

#[derive(Debug, Clone)]
struct StageState {
    index: usize,
    touched_at: f64,
}

#[derive(Debug, Default)]
struct SkillState {
    skills: HashMap<String, SkillSpec>,
    cell_bindings: HashMap<String, BTreeSet<String>>,
    stage_sessions: HashMap<(String, String), StageState>,
    revision: u64,
    registers: u64,
    replacements: u64,
    deletes: u64,
    usage_bumps: u64,
}

/// Thread-safe Rust-owned skill registry.
pub struct SkillRegistry {
    policy: RwLock<SkillPolicy>,
    content_policy: RwLock<SkillContentPolicy>,
    state: Mutex<SkillState>,
}

impl SkillRegistry {
    /// Construct an empty registry after validating policy inputs.
    pub fn new(policy: SkillPolicy) -> Result<Self, SkillError> {
        policy.validate()?;
        Ok(Self {
            policy: RwLock::new(policy),
            content_policy: RwLock::new(SkillContentPolicy::default()),
            state: Mutex::new(SkillState::default()),
        })
    }

    /// Install a host-supplied content contract.
    pub fn set_content_policy(&self, policy: SkillContentPolicy) {
        *self
            .content_policy
            .write()
            .unwrap_or_else(PoisonError::into_inner) = policy;
    }

    /// Return a copy of the current mechanism policy.
    pub fn policy(&self) -> SkillPolicy {
        self.policy
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    /// Replace the mechanism policy after validating it.
    pub fn set_policy(&self, policy: SkillPolicy) -> Result<(), SkillError> {
        policy.validate()?;
        let mut state = self.lock_state();
        if state.skills.len() > policy.max_skills {
            return Err(SkillError::Capacity(
                "new policy is smaller than current registry".to_owned(),
            ));
        }
        *self.policy.write().unwrap_or_else(PoisonError::into_inner) = policy;
        state
            .stage_sessions
            .retain(|_, value| value.touched_at.is_finite());
        Ok(())
    }

    /// Check whether a principal may perform a structural write.
    pub fn authorize_write(&self, principal: &SkillPrincipal) -> Result<String, SkillError> {
        let policy = self.policy();
        if principal.internal {
            return Ok("internal".to_owned());
        }
        if principal.agent_id.trim().is_empty() && principal.role.trim().is_empty() {
            return Err(SkillError::PermissionDenied(
                "identity required: provide agent_id or role".to_owned(),
            ));
        }
        let role = principal.effective_role();
        if principal.clearance >= policy.write_min_clearance
            || policy.write_roles.iter().any(|item| item == &role)
        {
            return Ok(role);
        }
        Err(SkillError::PermissionDenied(format!(
            "role '{role}' (clearance {}) lacks skill write clearance",
            principal.clearance
        )))
    }

    /// Register or replace a skill record under the write gate.
    pub fn register(
        &self,
        principal: &SkillPrincipal,
        skill: SkillSpec,
    ) -> Result<RegisterOutcome, SkillError> {
        let actor = self.authorize_write(principal)?;
        let policy = self.policy();
        let bounded = skill.bounded(&policy);
        bounded.validate(&policy)?;
        self.validate_content(&bounded)?;
        let mut state = self.lock_state();
        let existing = state.skills.get(&bounded.name).cloned();
        if let Some(previous) = existing.as_ref() {
            if previous.builtin && !principal.internal {
                return Err(SkillError::BuiltinReadOnly(bounded.name));
            }
        } else if state.skills.len() >= policy.max_skills {
            return Err(SkillError::Capacity("skill registry is full".to_owned()));
        }
        let outcome = if existing.is_some() {
            state.replacements = state.replacements.saturating_add(1);
            RegisterOutcome::Replaced
        } else {
            state.registers = state.registers.saturating_add(1);
            RegisterOutcome::Inserted
        };
        state.skills.insert(bounded.name.clone(), bounded.clone());
        state.revision = state.revision.saturating_add(1);
        drop(state);
        let _ = actor;
        Ok(outcome)
    }

    /// Return the result of a registration operation.
    pub fn register_report(
        &self,
        principal: &SkillPrincipal,
        skill: SkillSpec,
    ) -> Result<Value, SkillError> {
        let outcome = self.register(principal, skill.clone())?;
        Ok(json!({
            "success": true,
            "skill": skill.name,
            "outcome": outcome.as_str(),
            "revision": self.revision(),
        }))
    }

    /// Remove one non-builtin skill and its Cell bindings.
    pub fn delete(&self, principal: &SkillPrincipal, name: &str) -> Result<(), SkillError> {
        self.authorize_write(principal)?;
        let mut state = self.lock_state();
        let Some(skill) = state.skills.get(name) else {
            return Err(SkillError::NotFound(name.to_owned()));
        };
        if skill.builtin && !principal.internal {
            return Err(SkillError::BuiltinReadOnly(name.to_owned()));
        }
        state.skills.remove(name);
        for names in state.cell_bindings.values_mut() {
            names.remove(name);
        }
        state.cell_bindings.retain(|_, names| !names.is_empty());
        state
            .stage_sessions
            .retain(|(skill_name, _), _| skill_name != name);
        state.deletes = state.deletes.saturating_add(1);
        state.revision = state.revision.saturating_add(1);
        Ok(())
    }

    /// Update only usage bookkeeping; every caller may use this method.
    pub fn bump_usage(
        &self,
        name: &str,
        useful: bool,
        dimension: &str,
        now: f64,
    ) -> Result<u64, SkillError> {
        if !now.is_finite() {
            return Err(SkillError::Invalid(
                "usage timestamp must be finite".to_owned(),
            ));
        }
        let mut state = self.lock_state();
        let usage_count = {
            let skill = state
                .skills
                .get_mut(name)
                .ok_or_else(|| SkillError::NotFound(name.to_owned()))?;
            skill.usage_count = skill.usage_count.saturating_add(1);
            if useful {
                skill.useful_count = skill.useful_count.saturating_add(1);
            }
            skill.last_used = now;
            if !dimension.trim().is_empty() {
                let entry = skill
                    .usage_by_dimension
                    .entry(dimension.trim().to_owned())
                    .or_default();
                *entry = entry.saturating_add(1);
            }
            skill.usage_count
        };
        state.usage_bumps = state.usage_bumps.saturating_add(1);
        Ok(usage_count)
    }

    /// Return one cloned skill record.
    pub fn get(&self, name: &str) -> Option<SkillSpec> {
        self.lock_state().skills.get(name).cloned()
    }

    /// Return whether the registry contains a skill.
    pub fn contains(&self, name: &str) -> bool {
        self.lock_state().skills.contains_key(name)
    }

    /// Bind a registered skill to a Cell.
    pub fn bind_skill(
        &self,
        principal: &SkillPrincipal,
        cell_id: &str,
        name: &str,
    ) -> Result<(), SkillError> {
        self.authorize_write(principal)?;
        if cell_id.trim().is_empty() || name.trim().is_empty() {
            return Err(SkillError::Invalid(
                "cell_id and skill name are required".to_owned(),
            ));
        }
        let mut state = self.lock_state();
        if !state.skills.contains_key(name) {
            return Err(SkillError::NotFound(name.to_owned()));
        }
        state
            .cell_bindings
            .entry(cell_id.to_owned())
            .or_default()
            .insert(name.to_owned());
        state.revision = state.revision.saturating_add(1);
        Ok(())
    }

    /// Remove a Cell-to-skill binding.
    pub fn unbind_skill(
        &self,
        principal: &SkillPrincipal,
        cell_id: &str,
        name: &str,
    ) -> Result<(), SkillError> {
        self.authorize_write(principal)?;
        let mut state = self.lock_state();
        let Some(names) = state.cell_bindings.get_mut(cell_id) else {
            return Err(SkillError::NotFound(format!("{cell_id}/{name}")));
        };
        if !names.remove(name) {
            return Err(SkillError::NotFound(format!("{cell_id}/{name}")));
        }
        if names.is_empty() {
            state.cell_bindings.remove(cell_id);
        }
        state.revision = state.revision.saturating_add(1);
        Ok(())
    }

    /// Return the explicitly bound names for one Cell.
    pub fn skills_for_cell(&self, cell_id: &str) -> BTreeSet<String> {
        self.lock_state()
            .cell_bindings
            .get(cell_id)
            .cloned()
            .unwrap_or_default()
    }

    /// Return Cell identities that bind one skill.
    pub fn cells_for_skill(&self, name: &str) -> Vec<String> {
        self.lock_state()
            .cell_bindings
            .iter()
            .filter_map(|(cell, names)| names.contains(name).then_some(cell.clone()))
            .collect()
    }

    /// Return whether a skill passes lifecycle, binding, posture, and audience gates.
    pub fn skill_is_injectable(&self, name: &str, context: &InjectionContext) -> bool {
        let policy = self.policy();
        let state = self.lock_state();
        let Some(skill) = state.skills.get(name) else {
            return false;
        };
        if !skill.status.injectable()
            || matches!(
                skill.status,
                SkillStatus::Draft | SkillStatus::Retired | SkillStatus::Deprecated
            )
            || skill.disable_model_invocation
        {
            return false;
        }
        if skill.posture == SkillPosture::Offensive
            && policy.offensive_enabled
            && !policy
                .offensive_natures
                .iter()
                .any(|nature| nature == &context.posture)
            && !context.card_natures.iter().any(|nature| {
                policy
                    .offensive_natures
                    .iter()
                    .any(|allowed| allowed == nature)
            })
        {
            return false;
        }
        if skill.status == SkillStatus::Canary && !has_explicit_target(skill) {
            return false;
        }
        if !scope_matches(skill, context) {
            return false;
        }
        if policy.audience_filter_enabled && !audience_matches(skill, context) {
            return false;
        }
        if skill.disclosure == SkillDisclosure::None {
            return false;
        }
        true
    }

    /// List catalog rows with tag/layer/audience filters and deterministic sorting.
    pub fn list(&self, filter: &SkillListFilter, sort: SkillSort) -> Vec<SkillSummary> {
        let policy = self.policy();
        let state = self.lock_state();
        let mut rows = state
            .skills
            .values()
            .filter(|skill| {
                (filter.layer.trim().is_empty() || skill.layer == filter.layer)
                    && (filter.tags.is_empty()
                        || filter
                            .tags
                            .iter()
                            .any(|tag| skill.tags.iter().any(|item| item == tag)))
                    && (!filter.apply_audience_filter || audience_matches(skill, &filter.context))
                    && skill.disclosure != SkillDisclosure::None
            })
            .map(|skill| summary(skill, filter.include_prompt, policy.description_limit))
            .collect::<Vec<_>>();
        match sort {
            SkillSort::LoadedAt => rows.sort_by(|left, right| {
                right
                    .loaded_at
                    .total_cmp(&left.loaded_at)
                    .then_with(|| left.name.cmp(&right.name))
            }),
            SkillSort::LastUsed => rows.sort_by(|left, right| {
                right
                    .last_used
                    .total_cmp(&left.last_used)
                    .then_with(|| left.name.cmp(&right.name))
            }),
            SkillSort::Priority => rows.sort_by(|left, right| {
                right
                    .priority
                    .cmp(&left.priority)
                    .then_with(|| left.name.cmp(&right.name))
            }),
            SkillSort::Name => rows.sort_by(|left, right| left.name.cmp(&right.name)),
        }
        let limit = if filter.limit == 0 {
            if policy.full_index_enabled {
                policy.full_index_limit
            } else {
                rows.len()
            }
        } else {
            filter.limit
        };
        rows.truncate(limit);
        rows
    }

    /// Return all rules from skills whose names contain a domain fragment.
    pub fn rules_for(&self, domain: &str) -> Vec<String> {
        let domain = domain.to_ascii_lowercase();
        let state = self.lock_state();
        state
            .skills
            .iter()
            .filter(|(name, _)| domain.is_empty() || name.to_ascii_lowercase().contains(&domain))
            .flat_map(|(_, skill)| skill.rules.clone())
            .collect()
    }

    /// Return skills compatible with one requested tool.
    pub fn list_by_allowed_tool(&self, tool_name: &str) -> Vec<SkillSummary> {
        let state = self.lock_state();
        let mut rows = state
            .skills
            .values()
            .filter(|skill| {
                skill
                    .allowed_tools
                    .as_ref()
                    .is_none_or(|tools| tools.iter().any(|tool| tool == tool_name))
            })
            .map(|skill| summary(skill, false, DEFAULT_DESCRIPTION_LIMIT))
            .collect::<Vec<_>>();
        rows.sort_by(|left, right| left.name.cmp(&right.name));
        rows
    }

    /// Query skills with weighted deterministic keyword scoring.
    pub fn query(&self, question: &str) -> Vec<SkillSearchResult> {
        let terms = tokenize(question);
        if terms.is_empty() {
            return Vec::new();
        }
        let state = self.lock_state();
        let mut results = Vec::new();
        for skill in state.skills.values() {
            let mut score = 0.0;
            for term in &terms {
                score += 3.0 * count_occurrences(&skill.name, term);
                score += 2.0 * count_occurrences(&skill.description, term);
                for rule in &skill.rules {
                    score += count_occurrences(rule, term);
                }
                score += 0.5 * count_occurrences(&skill.prompt, term);
            }
            if score > 0.0 {
                results.push(SkillSearchResult {
                    name: skill.name.clone(),
                    score: (score * 10.0).round() / 10.0,
                    skill: skill.clone(),
                });
            }
        }
        results.sort_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.name.cmp(&right.name))
        });
        results
    }

    /// Return a deterministic `/skills/` virtual listing.
    pub fn vfs_content(&self) -> String {
        let state = self.lock_state();
        let mut names = state.skills.keys().cloned().collect::<Vec<_>>();
        names.sort();
        if names.is_empty() {
            return "(no skills loaded)".to_owned();
        }
        names
            .into_iter()
            .filter_map(|name| state.skills.get(&name))
            .map(|skill| {
                let description = skill.description.chars().take(50).collect::<String>();
                format!(
                    "{:<30} {:<50} [{} rules]",
                    skill.name,
                    description,
                    skill.rules.len()
                )
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// Return a structured agent-facing projection.
    pub fn structured(
        &self,
        name: &str,
        session_key: &str,
        now: f64,
    ) -> Result<StructuredSkill, SkillError> {
        let skill = self
            .get(name)
            .ok_or_else(|| SkillError::NotFound(name.to_owned()))?;
        let stage = if skill.stages.is_empty() {
            None
        } else {
            Some(self.current_stage(name, session_key, now)?)
        };
        Ok(StructuredSkill {
            success: true,
            name: skill.name,
            description: skill.description,
            rules: skill.rules,
            procedures: skill.procedures,
            allowed_tools: skill.allowed_tools.unwrap_or_default(),
            variables: skill.variables,
            dependencies: skill.dependencies,
            next: skill.next,
            disclosure: skill.disclosure,
            status: skill.status,
            stage,
        })
    }

    /// Read the current staged guidance cursor for one session.
    pub fn current_stage(
        &self,
        name: &str,
        session_key: &str,
        now: f64,
    ) -> Result<StageView, SkillError> {
        if !now.is_finite() {
            return Err(SkillError::Invalid(
                "stage timestamp must be finite".to_owned(),
            ));
        }
        let policy = self.policy();
        let mut state = self.lock_state();
        prune_stage_sessions(&mut state, now, &policy);
        let stage_len = state
            .skills
            .get(name)
            .ok_or_else(|| SkillError::NotFound(name.to_owned()))?
            .stages
            .len();
        if policy.guidance_mode == GuidanceMode::Small || stage_len == 0 {
            return Ok(StageView {
                skill: name.to_owned(),
                staged: false,
                stage_index: 0,
                stage: SkillStage {
                    id: String::new(),
                    name: String::new(),
                    instructions: String::new(),
                    completion: String::new(),
                },
                next_stage: None,
                done: true,
            });
        }
        let key = (name.to_owned(), session_key.to_owned());
        let index = state
            .stage_sessions
            .get(&key)
            .map(|entry| entry.index)
            .unwrap_or(0);
        if session_key.starts_with("card:") {
            if state.stage_sessions.len() >= policy.max_stage_sessions
                && !state.stage_sessions.contains_key(&key)
            {
                return Err(SkillError::Capacity(
                    "stage session registry is full".to_owned(),
                ));
            }
            state.stage_sessions.entry(key).or_insert(StageState {
                index: 0,
                touched_at: now,
            });
        }
        let index = index.min(stage_len.saturating_sub(1));
        let (stage, next_stage) = {
            let skill = state
                .skills
                .get(name)
                .ok_or_else(|| SkillError::NotFound(name.to_owned()))?;
            (
                skill.stages[index].clone(),
                skill.stages.get(index + 1).map(|item| item.id.clone()),
            )
        };
        Ok(StageView {
            skill: name.to_owned(),
            staged: true,
            stage_index: index,
            next_stage,
            done: index + 1 >= stage_len,
            stage,
        })
    }

    /// Advance one staged skill/session pair.
    pub fn advance_stage(
        &self,
        name: &str,
        session_key: &str,
        now: f64,
    ) -> Result<StageView, SkillError> {
        if !now.is_finite() {
            return Err(SkillError::Invalid(
                "stage timestamp must be finite".to_owned(),
            ));
        }
        let policy = self.policy();
        let mut state = self.lock_state();
        prune_stage_sessions(&mut state, now, &policy);
        let stage_len = state
            .skills
            .get(name)
            .ok_or_else(|| SkillError::NotFound(name.to_owned()))?
            .stages
            .len();
        if policy.guidance_mode == GuidanceMode::Small || stage_len == 0 {
            return self.current_stage_locked(&mut state, name, session_key, now);
        }
        let key = (name.to_owned(), session_key.to_owned());
        {
            let entry = state.stage_sessions.entry(key).or_insert(StageState {
                index: 0,
                touched_at: now,
            });
            if entry.index + 1 < stage_len {
                entry.index += 1;
            }
            entry.touched_at = now;
        }
        self.current_stage_locked(&mut state, name, session_key, now)
    }

    /// Advance all card-scoped staged skills after a completed card.
    pub fn on_card_complete(
        &self,
        card_id: &str,
        state_name: &str,
        now: f64,
    ) -> Result<usize, SkillError> {
        if !now.is_finite() {
            return Err(SkillError::Invalid(
                "card completion timestamp must be finite".to_owned(),
            ));
        }
        if !state_name.is_empty()
            && !matches!(
                state_name.to_ascii_uppercase().as_str(),
                "COMPLETED" | "DONE"
            )
        {
            return Ok(0);
        }
        let policy = self.policy();
        let mut state = self.lock_state();
        if policy.guidance_mode == GuidanceMode::Small {
            return Ok(0);
        }
        prune_stage_sessions(&mut state, now, &policy);
        let session_key = format!("card:{card_id}");
        let names = state
            .stage_sessions
            .keys()
            .filter(|(_, key)| key == &session_key)
            .map(|(name, _)| name.clone())
            .collect::<Vec<_>>();
        let mut advanced = 0;
        for name in names {
            let Some(stage_len) = state.skills.get(&name).map(|skill| skill.stages.len()) else {
                continue;
            };
            let key = (name, session_key.clone());
            let Some(cursor) = state.stage_sessions.get_mut(&key) else {
                continue;
            };
            if cursor.index + 1 < stage_len {
                cursor.index += 1;
                advanced += 1;
            }
            cursor.touched_at = now;
        }
        Ok(advanced)
    }

    /// Detect cycles in dependency and forward-guidance edges.
    pub fn validate_guidance_graph(&self) -> GuidanceGraphReport {
        let state = self.lock_state();
        let graph = guidance_graph(&state.skills);
        let mut colors: HashMap<String, u8> = HashMap::new();
        let mut stack = Vec::new();
        let mut cycles = Vec::new();
        for node in graph.keys() {
            if colors.get(node).copied().unwrap_or(0) == 0 {
                visit_graph(node, &graph, &mut colors, &mut stack, &mut cycles);
            }
        }
        GuidanceGraphReport {
            acyclic: cycles.is_empty(),
            cycles,
            nodes: graph.len(),
        }
    }

    /// Return currently unlocked skills under dependency prerequisites.
    pub fn guided_frontier(&self, completed: &[String]) -> Vec<String> {
        let guidance_mode = self.policy().guidance_mode;
        let state = self.lock_state();
        let completed = completed.iter().collect::<BTreeSet<_>>();
        let mut frontier = state
            .skills
            .values()
            .filter(|skill| skill.disclosure != SkillDisclosure::None)
            .filter(|skill| {
                guidance_mode == GuidanceMode::Small
                    || skill
                        .dependencies
                        .iter()
                        .all(|dependency| completed.contains(dependency))
            })
            .map(|skill| skill.name.clone())
            .collect::<Vec<_>>();
        frontier.sort();
        frontier
    }

    /// Return a prerequisite-first path to one target skill.
    pub fn guided_path(&self, target: &str) -> Vec<String> {
        let state = self.lock_state();
        let mut dependencies = BTreeMap::new();
        for (name, skill) in &state.skills {
            dependencies.insert(name.clone(), skill.dependencies.clone());
        }
        let mut queue = VecDeque::from([target.to_owned()]);
        let mut seen = BTreeSet::new();
        let mut path = Vec::new();
        while let Some(node) = queue.pop_front() {
            if !seen.insert(node.clone()) || !state.skills.contains_key(&node) {
                continue;
            }
            path.push(node.clone());
            if let Some(items) = dependencies.get(&node) {
                queue.extend(items.iter().cloned());
            }
        }
        path.reverse();
        path
    }

    /// Return a consistent checkpoint snapshot with deterministic ordering.
    pub fn checkpoint(&self, now: f64) -> Result<SkillCheckpoint, SkillError> {
        if !now.is_finite() {
            return Err(SkillError::Invalid(
                "checkpoint timestamp must be finite".to_owned(),
            ));
        }
        let state = self.lock_state();
        let mut skills = state.skills.values().cloned().collect::<Vec<_>>();
        skills.sort_by(|left, right| left.name.cmp(&right.name));
        let cell_bindings = state
            .cell_bindings
            .iter()
            .map(|(cell, names)| (cell.clone(), names.iter().cloned().collect()))
            .collect::<BTreeMap<_, _>>();
        let mut stage_sessions = state
            .stage_sessions
            .iter()
            .map(|((skill, session_key), entry)| StageSessionRecord {
                skill: skill.clone(),
                session_key: session_key.clone(),
                stage_index: entry.index,
                touched_at: entry.touched_at,
            })
            .collect::<Vec<_>>();
        stage_sessions.sort_by(|left, right| {
            left.skill
                .cmp(&right.skill)
                .then_with(|| left.session_key.cmp(&right.session_key))
        });
        Ok(SkillCheckpoint {
            document_version: SKILL_DOCUMENT_VERSION,
            revision: state.revision,
            skills,
            cell_bindings,
            stage_sessions,
        })
    }

    /// Validate and replace registry state from a Rust-owned checkpoint.
    pub fn restore(&self, checkpoint: SkillCheckpoint) -> Result<(), SkillError> {
        if checkpoint.document_version != SKILL_DOCUMENT_VERSION {
            return Err(SkillError::Invalid(
                "unsupported skill checkpoint version".to_owned(),
            ));
        }
        let policy = self.policy();
        if checkpoint.skills.len() > policy.max_skills {
            return Err(SkillError::Capacity(
                "checkpoint contains too many skills".to_owned(),
            ));
        }
        let mut skills = HashMap::new();
        for skill in checkpoint.skills {
            let bounded = skill.bounded(&policy);
            bounded.validate(&policy)?;
            self.validate_content(&bounded)?;
            if skills.insert(bounded.name.clone(), bounded).is_some() {
                return Err(SkillError::Invalid(
                    "checkpoint contains duplicate skill names".to_owned(),
                ));
            }
        }
        let mut bindings = HashMap::new();
        for (cell, names) in checkpoint.cell_bindings {
            if cell.trim().is_empty() || cell.contains('\0') {
                return Err(SkillError::Invalid(
                    "checkpoint contains invalid Cell identity".to_owned(),
                ));
            }
            let mut set = BTreeSet::new();
            for name in names {
                if !skills.contains_key(&name) {
                    return Err(SkillError::Invalid(format!(
                        "checkpoint binding references unknown skill '{name}'"
                    )));
                }
                set.insert(name);
            }
            if !set.is_empty() {
                bindings.insert(cell, set);
            }
        }
        let mut stage_sessions = HashMap::new();
        if checkpoint.stage_sessions.len() > policy.max_stage_sessions {
            return Err(SkillError::Capacity(
                "checkpoint contains too many stage sessions".to_owned(),
            ));
        }
        for record in checkpoint.stage_sessions {
            if !record.touched_at.is_finite() || record.session_key.is_empty() {
                return Err(SkillError::Invalid(
                    "checkpoint contains invalid stage session".to_owned(),
                ));
            }
            let Some(skill) = skills.get(&record.skill) else {
                return Err(SkillError::Invalid(
                    "checkpoint stage references unknown skill".to_owned(),
                ));
            };
            if record.stage_index >= skill.stages.len() && !skill.stages.is_empty() {
                return Err(SkillError::Invalid(
                    "checkpoint stage index is out of range".to_owned(),
                ));
            }
            if stage_sessions
                .insert(
                    (record.skill, record.session_key),
                    StageState {
                        index: record.stage_index,
                        touched_at: record.touched_at,
                    },
                )
                .is_some()
            {
                return Err(SkillError::Invalid(
                    "checkpoint contains duplicate stage sessions".to_owned(),
                ));
            }
        }
        let mut state = self.lock_state();
        state.skills = skills;
        state.cell_bindings = bindings;
        state.stage_sessions = stage_sessions;
        state.revision = checkpoint.revision;
        state.registers = 0;
        state.replacements = 0;
        state.deletes = 0;
        state.usage_bumps = 0;
        Ok(())
    }

    /// Return current registry counters.
    pub fn stats(&self) -> SkillStats {
        let state = self.lock_state();
        SkillStats {
            total: state.skills.len(),
            revision: state.revision,
            registers: state.registers,
            replacements: state.replacements,
            deletes: state.deletes,
            usage_bumps: state.usage_bumps,
            cell_bindings: state.cell_bindings.values().map(BTreeSet::len).sum(),
            stage_sessions: state.stage_sessions.len(),
        }
    }

    /// Return the structural revision.
    pub fn revision(&self) -> u64 {
        self.lock_state().revision
    }

    /// Clear every record and return the number removed.
    pub fn clear(&self, principal: &SkillPrincipal) -> Result<usize, SkillError> {
        self.authorize_write(principal)?;
        let mut state = self.lock_state();
        let count = state.skills.len();
        state.skills.clear();
        state.cell_bindings.clear();
        state.stage_sessions.clear();
        state.revision = state.revision.saturating_add(1);
        Ok(count)
    }

    fn validate_content(&self, skill: &SkillSpec) -> Result<(), SkillError> {
        let policy = self
            .content_policy
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .clone();
        let mut content = String::new();
        content.push_str(&skill.prompt);
        content.push('\n');
        content.push_str(&skill.description);
        for rule in &skill.rules {
            content.push('\n');
            content.push_str(rule);
        }
        let lower = content.to_ascii_lowercase();
        let mut violations = Vec::new();
        for pattern in &policy.forbidden_patterns {
            if lower.contains(&pattern.to_ascii_lowercase()) {
                violations.push(format!("constitutional pattern: {pattern}"));
            }
        }
        for literal in &policy.forbidden_literals {
            if content.contains(literal) {
                violations.push(format!("project-specific literal: {literal}"));
            }
        }
        if violations.is_empty() {
            Ok(())
        } else {
            Err(SkillError::ContentViolation(violations))
        }
    }

    fn current_stage_locked(
        &self,
        state: &mut SkillState,
        name: &str,
        session_key: &str,
        now: f64,
    ) -> Result<StageView, SkillError> {
        let policy = self.policy();
        let skill = state
            .skills
            .get(name)
            .ok_or_else(|| SkillError::NotFound(name.to_owned()))?;
        if policy.guidance_mode == GuidanceMode::Small || skill.stages.is_empty() {
            return Ok(StageView {
                skill: name.to_owned(),
                staged: false,
                stage_index: 0,
                stage: SkillStage {
                    id: String::new(),
                    name: String::new(),
                    instructions: String::new(),
                    completion: String::new(),
                },
                next_stage: None,
                done: true,
            });
        }
        let key = (name.to_owned(), session_key.to_owned());
        let index = state
            .stage_sessions
            .get(&key)
            .map(|entry| entry.index)
            .unwrap_or(0);
        state.stage_sessions.entry(key).or_insert(StageState {
            index,
            touched_at: now,
        });
        let index = index.min(skill.stages.len().saturating_sub(1));
        Ok(StageView {
            skill: name.to_owned(),
            staged: true,
            stage_index: index,
            stage: skill.stages[index].clone(),
            next_stage: skill.stages.get(index + 1).map(|item| item.id.clone()),
            done: index + 1 >= skill.stages.len(),
        })
    }

    fn lock_state(&self) -> MutexGuard<'_, SkillState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// Registration outcome exposed to host adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RegisterOutcome {
    /// A new record was inserted.
    Inserted,
    /// A non-builtin record was replaced.
    Replaced,
}

impl RegisterOutcome {
    /// Return the stable wire spelling.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Inserted => "inserted",
            Self::Replaced => "replaced",
        }
    }
}

fn normalize_strings(values: Vec<String>, limit: usize) -> Vec<String> {
    let mut normalized = BTreeSet::new();
    for value in values {
        let trimmed = value.trim();
        if !trimmed.is_empty() && !trimmed.contains('\0') {
            normalized.insert(trimmed.to_owned());
        }
    }
    normalized.into_iter().take(limit).collect()
}

fn summary(skill: &SkillSpec, include_prompt: bool, description_limit: usize) -> SkillSummary {
    SkillSummary {
        name: skill.name.clone(),
        description: skill.description.chars().take(description_limit).collect(),
        rules: skill.rules.len(),
        procedures: skill.procedures.len(),
        tags: skill.tags.clone(),
        prompt: if include_prompt {
            skill.prompt.clone()
        } else {
            String::new()
        },
        source: skill.source.clone(),
        builtin: skill.builtin,
        posture: skill.posture,
        status: skill.status,
        disclosure: skill.disclosure,
        stages: skill.stages.len(),
        next: skill.next.clone(),
        loaded_at: skill.loaded_at,
        last_used: skill.last_used,
        disable_model_invocation: skill.disable_model_invocation,
        dependencies: skill.dependencies.clone(),
        dependency_kind: skill.dependency_kind,
        layer: skill.layer.clone(),
        scope: skill.scope,
        scope_identity: skill.scope_identity.clone(),
        priority: skill.priority,
    }
}

fn has_explicit_target(skill: &SkillSpec) -> bool {
    skill.scope != SkillScope::Global
        || !skill.scope_identity.trim().is_empty()
        || skill
            .tags
            .iter()
            .any(|tag| tag.starts_with("agent:") || tag.starts_with("cell:"))
}

fn scope_matches(skill: &SkillSpec, context: &InjectionContext) -> bool {
    match skill.scope {
        SkillScope::Global => true,
        SkillScope::Agent => {
            !skill.scope_identity.is_empty() && skill.scope_identity == context.agent_id
        }
        SkillScope::Cell => {
            !skill.scope_identity.is_empty() && skill.scope_identity == context.cell_id
        }
    }
}

fn audience_matches(skill: &SkillSpec, context: &InjectionContext) -> bool {
    let tags = skill
        .tags
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let tagged = tags.contains("strategy") || tags.contains("execution");
    if !tagged {
        return true;
    }
    let strategy = context.role == "l3a" || context.agent_id == "l3a";
    (strategy && tags.contains("strategy")) || (!strategy && tags.contains("execution"))
}

fn tokenize(value: &str) -> BTreeSet<String> {
    value
        .to_ascii_lowercase()
        .split(|character: char| character.is_whitespace() || ",;:._-".contains(character))
        .filter(|term| !term.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

fn count_occurrences(value: &str, term: &str) -> f64 {
    let value = value.to_ascii_lowercase();
    let mut remaining = value.as_str();
    let mut count = 0_u64;
    while let Some(index) = remaining.find(term) {
        count = count.saturating_add(1);
        remaining = &remaining[index + term.len()..];
    }
    count as f64
}

fn guidance_graph(skills: &HashMap<String, SkillSpec>) -> BTreeMap<String, BTreeSet<String>> {
    let mut graph: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for (name, skill) in skills {
        graph.entry(name.clone()).or_default();
        for dependency in &skill.dependencies {
            graph
                .entry(dependency.clone())
                .or_default()
                .insert(name.clone());
        }
        for next in &skill.next {
            graph.entry(name.clone()).or_default().insert(next.clone());
            graph.entry(next.clone()).or_default();
        }
    }
    graph
}

fn visit_graph(
    node: &str,
    graph: &BTreeMap<String, BTreeSet<String>>,
    colors: &mut HashMap<String, u8>,
    stack: &mut Vec<String>,
    cycles: &mut Vec<Vec<String>>,
) {
    colors.insert(node.to_owned(), 1);
    stack.push(node.to_owned());
    if let Some(children) = graph.get(node) {
        for child in children {
            match colors.get(child).copied().unwrap_or(0) {
                0 => visit_graph(child, graph, colors, stack, cycles),
                1 => {
                    if let Some(index) = stack.iter().position(|item| item == child) {
                        cycles.push(
                            stack[index..]
                                .iter()
                                .cloned()
                                .chain([child.clone()])
                                .collect(),
                        );
                    }
                }
                _ => {}
            }
        }
    }
    stack.pop();
    colors.insert(node.to_owned(), 2);
}

fn prune_stage_sessions(state: &mut SkillState, now: f64, policy: &SkillPolicy) {
    let over_capacity = state.stage_sessions.len() > policy.max_stage_sessions;
    state
        .stage_sessions
        .retain(|_, entry| !over_capacity || now - entry.touched_at < policy.stage_state_ttl);
    if state.stage_sessions.len() > policy.max_stage_sessions {
        let mut entries = state
            .stage_sessions
            .iter()
            .map(|(key, entry)| (key.clone(), entry.touched_at))
            .collect::<Vec<_>>();
        entries.sort_by(|left, right| left.1.total_cmp(&right.1));
        let remove_count = state.stage_sessions.len() - policy.max_stage_sessions;
        for (key, _) in entries.into_iter().take(remove_count) {
            state.stage_sessions.remove(&key);
        }
    }
}

impl Default for SkillRegistry {
    /// Construct a registry with the default policy.
    fn default() -> Self {
        Self::new(SkillPolicy::default()).expect("default skill policy is valid")
    }
}

/// Process-global adapter convenience, not production authority.
static GLOBAL_REGISTRY: std::sync::OnceLock<Mutex<Option<std::sync::Arc<SkillRegistry>>>> =
    std::sync::OnceLock::new();

fn global_registry() -> &'static Mutex<Option<std::sync::Arc<SkillRegistry>>> {
    GLOBAL_REGISTRY.get_or_init(|| Mutex::new(None))
}

/// Return the process-global registry for adapters/tests.
pub fn get_skill_registry() -> std::sync::Arc<SkillRegistry> {
    let mut slot = global_registry()
        .lock()
        .unwrap_or_else(PoisonError::into_inner);
    std::sync::Arc::clone(slot.get_or_insert_with(|| std::sync::Arc::new(SkillRegistry::default())))
}

/// Reset the process-global registry for controlled restart/test isolation.
pub fn reset_skill_registry() {
    *global_registry()
        .lock()
        .unwrap_or_else(PoisonError::into_inner) = None;
}
