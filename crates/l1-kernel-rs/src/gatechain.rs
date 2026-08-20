//! Rust candidate for the pure G1-G5 capability gate chain.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::{Mutex, PoisonError};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::contract::ProcessState;

/// Maximum ledger entries retained by the default candidate.
pub const GATECHAIN_LEDGER_MAX: usize = 200;
/// Maximum number of recent entries used by G5 history scoring.
pub const GATECHAIN_HISTORY_LIMIT: usize = 10;
/// Time window used by G3 frequency scoring.
pub const GATECHAIN_COUNT_WINDOW_SECONDS: f64 = 60.0;
/// Ring at or above which an unverified identity is blocked.
pub const GATECHAIN_REQUIRE_IDENTITY_RING: u8 = 2;
/// Default danger level for an unlisted capability.
pub const GATECHAIN_DEFAULT_DANGER: u8 = 1;
/// G3 frequency score multiplier.
pub const GATECHAIN_FREQ_MULTIPLIER: f64 = 0.5;
/// G3 score at or above which the step warns.
pub const GATECHAIN_RISK_WARN_THRESHOLD: f64 = 6.0;
/// G4 danger level at or above which explicit approval is required.
pub const GATECHAIN_ESCALATION_DANGER: u8 = 4;
/// G5 history length at or above which repetition is detected.
pub const GATECHAIN_REPEAT_THRESHOLD: usize = 5;
/// G5 same-tool count at or above which spinning is reported.
pub const GATECHAIN_HIGH_FREQ_THRESHOLD: usize = 3;
/// G5 danger score weight.
pub const GATECHAIN_DANGER_WEIGHT: f64 = 2.0;
/// G5 history length score weight.
pub const GATECHAIN_HISTORY_WEIGHT: f64 = 0.5;
/// G5 same-tool score weight.
pub const GATECHAIN_TOOL_FREQ_WEIGHT: f64 = 1.0;
/// Reputation at or above which a G3 warning is tolerated.
pub const GATECHAIN_REPUTATION_HIGH: f64 = 0.9;
/// Reputation below which a G3 warning blocks.
pub const GATECHAIN_REPUTATION_LOW: f64 = 0.7;
/// Default reputation supplied when the provider is outside the candidate.
pub const GATECHAIN_DEFAULT_REPUTATION: f64 = 0.85;

/// Stable four-state gate verdict mirrored from Python `GateResult`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum GateDecision {
    /// The call passed this gate.
    Pass,
    /// The call may continue with a warning.
    Warn,
    /// The call must stop.
    Block,
    /// The call is allowed but reported for follow-up.
    Report,
}

impl GateDecision {
    /// Return the stable wire spelling used by Python gate results.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pass => "PASS",
            Self::Warn => "WARN",
            Self::Block => "BLOCK",
            Self::Report => "REPORT",
        }
    }

    /// Return whether this verdict permits the call to continue.
    pub const fn allowed(self) -> bool {
        !matches!(self, Self::Block)
    }
}

/// Process identity snapshot supplied to G2 by an adapter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GateIdentity {
    /// Process identifier, if one exists.
    pub pid: u64,
    /// Agent ring used by the identity threshold.
    pub ring: u8,
    /// Lifecycle state at the gate boundary.
    pub state: ProcessState,
    /// Whether the identity proof was verified.
    pub verified: bool,
}

/// Inputs consumed by the pure gate chain. Providers and side effects stay outside.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GateRequest {
    /// Registered capability name.
    pub tool: String,
    /// Calling process or interactive principal.
    pub agent_id: String,
    /// Optional target path or resource.
    #[serde(default)]
    pub target: String,
    /// Card or territory roots; an empty list skips the optional check.
    #[serde(default)]
    pub territory: Vec<String>,
    /// Optional process identity snapshot for non-interactive callers.
    #[serde(default)]
    pub identity: Option<GateIdentity>,
    /// Clearance ring used for an interactive boundary principal.
    #[serde(default = "default_interactive_ring")]
    pub interactive_ring: u8,
    /// Optional danger override from an approval/tool policy adapter.
    #[serde(default)]
    pub danger_override: Option<u8>,
    /// Reputation supplied by an adapter; absent uses the stable default.
    #[serde(default)]
    pub reputation: Option<f64>,
    /// Whether an approval chain already authorized the call.
    #[serde(default)]
    pub pre_approved: bool,
    /// Whether the posture adapter explicitly granted full power.
    #[serde(default)]
    pub full_power: bool,
    /// Whether the harness adapter explicitly selected an auto-approval mode.
    #[serde(default)]
    pub harness_auto_approved: bool,
    /// Optional deterministic timestamp used by parity tests.
    #[serde(default)]
    pub timestamp: Option<f64>,
    /// Whether the caller was authenticated at an interactive boundary.
    #[serde(default)]
    pub interactive: bool,
}

impl GateRequest {
    /// Construct a request with the production-safe default inputs.
    pub fn new(tool: impl Into<String>, agent_id: impl Into<String>) -> Self {
        Self {
            tool: tool.into(),
            agent_id: agent_id.into(),
            target: String::new(),
            territory: Vec::new(),
            identity: None,
            interactive_ring: default_interactive_ring(),
            danger_override: None,
            reputation: None,
            pre_approved: false,
            full_power: false,
            harness_auto_approved: false,
            timestamp: None,
            interactive: false,
        }
    }
}

/// One structured gate step. Optional values avoid interpreter-specific maps.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GateStep {
    /// Gate identifier (`G1` through `G5`).
    pub gate: String,
    /// Gate verdict.
    pub result: GateDecision,
    /// Stable human-readable reason, empty for an ordinary pass.
    #[serde(default)]
    pub reason: String,
    /// G3 risk score, when the step computed one.
    #[serde(default)]
    pub risk_score: Option<f64>,
    /// G5 composite score, when the step computed one.
    #[serde(default)]
    pub score: Option<f64>,
    /// G5 reputation input, when the step computed one.
    #[serde(default)]
    pub reputation: Option<f64>,
    /// G2 process id, when supplied.
    #[serde(default)]
    pub pid: Option<u64>,
    /// G2 ring, when supplied.
    #[serde(default)]
    pub ring: Option<u8>,
    /// G2 interactive marker, when supplied.
    #[serde(default)]
    pub interactive: Option<bool>,
}

/// Final gate-chain result with all executed steps.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GateCheckResult {
    /// Whether execution may continue (`BLOCK` is the only denial).
    pub allowed: bool,
    /// Final four-state decision.
    pub decision: GateDecision,
    /// Ordered steps; later gates are absent after a block.
    pub steps: Vec<GateStep>,
}

/// Ledger row retained for G3/G5 frequency and history scoring.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GateLedgerEntry {
    /// Calling principal.
    pub agent_id: String,
    /// Capability name.
    pub tool: String,
    /// Target path or resource.
    pub target: String,
    /// Final gate result.
    pub result: GateDecision,
    /// Record timestamp in Unix seconds.
    pub timestamp: f64,
    /// Stable G1/G3 pattern identifier.
    #[serde(default)]
    pub pattern: String,
}

/// Bounded, thread-safe history ledger used by G3 and G5.
pub struct GateLedger {
    max_entries: usize,
    entries: Mutex<VecDeque<GateLedgerEntry>>,
}

impl GateLedger {
    /// Create a ledger with the default capacity.
    pub fn new() -> Self {
        Self::with_capacity(GATECHAIN_LEDGER_MAX)
    }

    /// Create a ledger with an explicit bounded capacity.
    pub fn with_capacity(max_entries: usize) -> Self {
        Self {
            max_entries,
            entries: Mutex::new(VecDeque::with_capacity(max_entries)),
        }
    }

    /// Append a row, evicting the oldest row when full.
    pub fn record(&self, entry: GateLedgerEntry) {
        let mut entries = self.lock_entries();
        if self.max_entries == 0 {
            entries.clear();
            return;
        }
        entries.push_back(entry);
        while entries.len() > self.max_entries {
            entries.pop_front();
        }
    }

    /// Return recent rows filtered by optional agent and tool.
    pub fn recent(&self, agent_id: &str, tool: &str, limit: usize) -> Vec<GateLedgerEntry> {
        if limit == 0 {
            return Vec::new();
        }
        let entries = self.lock_entries();
        entries
            .iter()
            .filter(|entry| {
                (agent_id.is_empty() || entry.agent_id == agent_id)
                    && (tool.is_empty() || entry.tool == tool)
            })
            .rev()
            .take(limit)
            .cloned()
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect()
    }

    /// Count rows for an agent/tool within the supplied time window.
    pub fn count(&self, agent_id: &str, tool: &str, now: f64, window_seconds: f64) -> usize {
        let entries = self.lock_entries();
        entries
            .iter()
            .filter(|entry| {
                (agent_id.is_empty() || entry.agent_id == agent_id)
                    && (tool.is_empty() || entry.tool == tool)
                    && now - entry.timestamp <= window_seconds
            })
            .count()
    }

    /// Remove all retained rows.
    pub fn clear(&self) {
        self.lock_entries().clear();
    }

    /// Return the number of retained rows.
    pub fn len(&self) -> usize {
        self.lock_entries().len()
    }

    /// Return whether the ledger contains no rows.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    fn lock_entries(&self) -> std::sync::MutexGuard<'_, VecDeque<GateLedgerEntry>> {
        self.entries.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl Default for GateLedger {
    fn default() -> Self {
        Self::new()
    }
}

/// Data-only thresholds and danger map supplied by configuration.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GatePolicy {
    /// Empty whitelist behavior.
    pub require_whitelist: bool,
    /// Tool-specific danger levels.
    #[serde(default)]
    pub danger_levels: BTreeMap<String, u8>,
    /// G2 identity threshold.
    pub require_identity_ring: u8,
    /// G3 default danger.
    pub default_danger: u8,
    /// G3 frequency multiplier.
    pub frequency_multiplier: f64,
    /// G3 warning threshold.
    pub risk_warn_threshold: f64,
    /// G4 escalation threshold.
    pub escalation_danger: u8,
    /// G5 history lookback limit.
    pub history_limit: usize,
    /// G5 repetition threshold.
    pub repeat_threshold: usize,
    /// G5 same-tool threshold.
    pub high_frequency_threshold: usize,
    /// G5 danger weight.
    pub danger_weight: f64,
    /// G5 history weight.
    pub history_weight: f64,
    /// G5 same-tool weight.
    pub tool_frequency_weight: f64,
    /// High reputation threshold.
    pub reputation_high: f64,
    /// Low reputation threshold.
    pub reputation_low: f64,
    /// Default reputation.
    pub default_reputation: f64,
    /// G3/G5 count window in seconds.
    pub count_window_seconds: f64,
}

impl Default for GatePolicy {
    fn default() -> Self {
        let danger_levels = BTreeMap::from([
            ("deploy".to_owned(), 5),
            ("db_migrate".to_owned(), 4),
            ("user_delete".to_owned(), 5),
            ("destroy".to_owned(), 5),
            ("rollback".to_owned(), 4),
            ("migrate".to_owned(), 4),
            ("exec".to_owned(), 4),
            ("run_in_terminal".to_owned(), 3),
            ("execute".to_owned(), 3),
            ("delete".to_owned(), 3),
            ("write".to_owned(), 2),
            ("replace".to_owned(), 2),
            ("format".to_owned(), 2),
        ]);
        Self {
            require_whitelist: true,
            danger_levels,
            require_identity_ring: GATECHAIN_REQUIRE_IDENTITY_RING,
            default_danger: GATECHAIN_DEFAULT_DANGER,
            frequency_multiplier: GATECHAIN_FREQ_MULTIPLIER,
            risk_warn_threshold: GATECHAIN_RISK_WARN_THRESHOLD,
            escalation_danger: GATECHAIN_ESCALATION_DANGER,
            history_limit: GATECHAIN_HISTORY_LIMIT,
            repeat_threshold: GATECHAIN_REPEAT_THRESHOLD,
            high_frequency_threshold: GATECHAIN_HIGH_FREQ_THRESHOLD,
            danger_weight: GATECHAIN_DANGER_WEIGHT,
            history_weight: GATECHAIN_HISTORY_WEIGHT,
            tool_frequency_weight: GATECHAIN_TOOL_FREQ_WEIGHT,
            reputation_high: GATECHAIN_REPUTATION_HIGH,
            reputation_low: GATECHAIN_REPUTATION_LOW,
            default_reputation: GATECHAIN_DEFAULT_REPUTATION,
            count_window_seconds: GATECHAIN_COUNT_WINDOW_SECONDS,
        }
    }
}

/// Pure G1-G5 candidate. Whitelist and ledger are the only mutable state.
pub struct GateChain {
    policy: GatePolicy,
    whitelist: Mutex<BTreeSet<String>>,
    whitelist_configured: Mutex<bool>,
    ledger: GateLedger,
}

impl GateChain {
    /// Create a candidate with the default policy and no whitelist.
    pub fn new() -> Self {
        Self::with_policy(GatePolicy::default())
    }

    /// Create a candidate with an explicit data-only policy.
    pub fn with_policy(policy: GatePolicy) -> Self {
        Self {
            policy,
            whitelist: Mutex::new(BTreeSet::new()),
            whitelist_configured: Mutex::new(false),
            ledger: GateLedger::new(),
        }
    }

    /// Register additional whitelist names using copy-on-write semantics.
    pub fn register_tools<I, S>(&self, tools: I)
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let mut whitelist = self
            .whitelist
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        whitelist.extend(tools.into_iter().map(Into::into));
        *self
            .whitelist_configured
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = true;
    }

    /// Replace the whitelist with the current registry names.
    pub fn replace_tools<I, S>(&self, tools: I)
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let mut whitelist = self
            .whitelist
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        whitelist.clear();
        whitelist.extend(tools.into_iter().map(Into::into));
        *self
            .whitelist_configured
            .lock()
            .unwrap_or_else(PoisonError::into_inner) = true;
    }

    /// Return a snapshot of the registered names.
    pub fn whitelist(&self) -> Vec<String> {
        self.whitelist
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .iter()
            .cloned()
            .collect()
    }

    /// Return the candidate ledger for inspection or an adapter bridge.
    pub const fn ledger(&self) -> &GateLedger {
        &self.ledger
    }

    /// Evaluate G1-G5 and append the final decision to the bounded ledger.
    pub fn check(&self, request: &GateRequest) -> GateCheckResult {
        let now = request.timestamp.unwrap_or_else(unix_timestamp);
        let whitelist = self
            .whitelist
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone();
        let configured = *self
            .whitelist_configured
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let mut steps = Vec::new();
        let mut overall = GateDecision::Pass;

        if (!configured || whitelist.is_empty()) && self.policy.require_whitelist {
            steps.push(step(
                "G1",
                GateDecision::Block,
                "no whitelist configured (fail-closed)",
            ));
            return self.finish(request, now, steps, GateDecision::Block);
        }
        if !configured || whitelist.is_empty() {
            steps.push(step("G1", GateDecision::Warn, "no whitelist configured"));
            overall = GateDecision::Warn;
        } else if !whitelist.contains(&request.tool) {
            steps.push(step("G1", GateDecision::Block, "tool not in whitelist"));
            return self.finish(request, now, steps, GateDecision::Block);
        } else {
            steps.push(step("G1", GateDecision::Pass, ""));
        }

        let g2 = self.check_identity(request);
        if g2.result == GateDecision::Block {
            steps.push(g2);
            return self.finish(request, now, steps, GateDecision::Block);
        }
        overall = retain_warning(overall, g2.result);
        steps.push(g2);

        let danger = request.danger_override.unwrap_or_else(|| {
            self.policy
                .danger_levels
                .get(&request.tool)
                .copied()
                .unwrap_or(self.policy.default_danger)
        });
        let recent_count = self.ledger.count(
            &request.agent_id,
            &request.tool,
            now,
            self.policy.count_window_seconds,
        );
        if !request.territory.is_empty()
            && !request.target.is_empty()
            && !path_within(&request.target, &request.territory)
        {
            steps.push(step(
                "G3",
                GateDecision::Block,
                "target is outside the declared territory",
            ));
            return self.finish(request, now, steps, GateDecision::Block);
        }
        let risk_score = f64::from(danger) + recent_count as f64 * self.policy.frequency_multiplier;
        let g3_result = if risk_score >= self.policy.risk_warn_threshold {
            overall = retain_warning(overall, GateDecision::Warn);
            GateDecision::Warn
        } else {
            GateDecision::Pass
        };
        steps.push(GateStep {
            gate: "G3".to_owned(),
            result: g3_result,
            reason: String::new(),
            risk_score: Some(risk_score),
            score: None,
            reputation: None,
            pid: None,
            ring: None,
            interactive: None,
        });

        let g4 = self.check_escalation(request, danger);
        if g4.result == GateDecision::Block {
            steps.push(g4);
            return self.finish(request, now, steps, GateDecision::Block);
        }
        overall = retain_warning(overall, g4.result);
        steps.push(g4);

        let history = self
            .ledger
            .recent(&request.agent_id, "", self.policy.history_limit);
        let same_tool_count = history
            .iter()
            .filter(|entry| entry.tool == request.tool)
            .count();
        let reputation = request
            .reputation
            .unwrap_or(self.policy.default_reputation)
            .clamp(0.0, 1.0);
        let score = f64::from(danger) * self.policy.danger_weight
            + history.len() as f64 * self.policy.history_weight
            + same_tool_count as f64 * self.policy.tool_frequency_weight;
        let repeated = history.len() >= self.policy.repeat_threshold;
        let high_frequency = same_tool_count >= self.policy.high_frequency_threshold;
        let g5_result =
            if reputation >= self.policy.reputation_high && g3_result == GateDecision::Warn {
                overall = GateDecision::Pass;
                GateDecision::Pass
            } else if reputation < self.policy.reputation_low && g3_result == GateDecision::Warn {
                GateDecision::Block
            } else if repeated && high_frequency {
                GateDecision::Report
            } else if repeated {
                if reputation < self.policy.reputation_low {
                    GateDecision::Report
                } else {
                    GateDecision::Warn
                }
            } else {
                GateDecision::Pass
            };
        if g5_result == GateDecision::Block {
            steps.push(g5_step(
                g5_result,
                score,
                reputation,
                "low reputation combined with G3 risk",
            ));
            return self.finish(request, now, steps, GateDecision::Block);
        }
        if g5_result == GateDecision::Report {
            overall = GateDecision::Report;
        }
        steps.push(g5_step(g5_result, score, reputation, ""));
        self.finish(request, now, steps, overall)
    }

    fn check_identity(&self, request: &GateRequest) -> GateStep {
        if request.interactive {
            return GateStep {
                gate: "G2".to_owned(),
                result: GateDecision::Pass,
                reason: String::new(),
                risk_score: None,
                score: None,
                reputation: None,
                pid: None,
                ring: Some(request.interactive_ring),
                interactive: Some(true),
            };
        }
        let Some(identity) = request.identity.as_ref() else {
            return step(
                "G2",
                GateDecision::Block,
                "agent is not registered in the process table",
            );
        };
        if !matches!(identity.state, ProcessState::Ready | ProcessState::Running) {
            return step(
                "G2",
                GateDecision::Block,
                "agent state is not READY/RUNNING",
            );
        }
        let result = if !identity.verified && identity.ring >= self.policy.require_identity_ring {
            GateDecision::Block
        } else if !identity.verified {
            GateDecision::Warn
        } else {
            GateDecision::Pass
        };
        let reason = if result == GateDecision::Block {
            "ring requires verified identity (fail-closed)"
        } else if result == GateDecision::Warn {
            "identity is not verified"
        } else {
            ""
        };
        GateStep {
            gate: "G2".to_owned(),
            result,
            reason: reason.to_owned(),
            risk_score: None,
            score: None,
            reputation: None,
            pid: Some(identity.pid),
            ring: Some(identity.ring),
            interactive: Some(false),
        }
    }

    fn check_escalation(&self, request: &GateRequest, danger: u8) -> GateStep {
        if danger < self.policy.escalation_danger {
            return step("G4", GateDecision::Pass, "");
        }
        if request.full_power {
            return step("G4", GateDecision::Pass, "full-power posture authorized");
        }
        if request.pre_approved || request.harness_auto_approved {
            return step("G4", GateDecision::Pass, "explicit authorization supplied");
        }
        step(
            "G4",
            GateDecision::Block,
            "high-danger call has no approval",
        )
    }

    fn finish(
        &self,
        request: &GateRequest,
        timestamp: f64,
        steps: Vec<GateStep>,
        decision: GateDecision,
    ) -> GateCheckResult {
        let g1 = steps.first().map_or("?", |step| step.result.as_str());
        let g3 = steps.get(2).map_or("?", |step| step.result.as_str());
        self.ledger.record(GateLedgerEntry {
            agent_id: request.agent_id.clone(),
            tool: request.tool.clone(),
            target: request.target.clone(),
            result: decision,
            timestamp,
            pattern: format!("G1-{g1}_G3-{g3}"),
        });
        GateCheckResult {
            allowed: decision.allowed(),
            decision,
            steps,
        }
    }
}

impl Default for GateChain {
    fn default() -> Self {
        Self::new()
    }
}

fn default_interactive_ring() -> u8 {
    1
}

fn step(gate: &str, result: GateDecision, reason: &str) -> GateStep {
    GateStep {
        gate: gate.to_owned(),
        result,
        reason: reason.to_owned(),
        risk_score: None,
        score: None,
        reputation: None,
        pid: None,
        ring: None,
        interactive: None,
    }
}

fn g5_step(result: GateDecision, score: f64, reputation: f64, reason: &str) -> GateStep {
    GateStep {
        gate: "G5".to_owned(),
        result,
        reason: reason.to_owned(),
        risk_score: None,
        score: Some(score),
        reputation: Some(reputation),
        pid: None,
        ring: None,
        interactive: None,
    }
}

fn retain_warning(current: GateDecision, next: GateDecision) -> GateDecision {
    if current == GateDecision::Warn || next == GateDecision::Warn {
        GateDecision::Warn
    } else {
        current
    }
}

pub(crate) fn path_within(target: &str, bases: &[String]) -> bool {
    crate::territory::is_within(target, bases)
}

fn unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs_f64())
}

#[cfg(test)]
mod tests {
    use super::{
        GATECHAIN_HISTORY_LIMIT, GateChain, GateDecision, GateIdentity, GateLedger,
        GateLedgerEntry, GateRequest,
    };
    use crate::contract::ProcessState;
    use serde::Deserialize;

    fn ready_identity(ring: u8, verified: bool) -> GateIdentity {
        GateIdentity {
            pid: 7,
            ring,
            state: ProcessState::Ready,
            verified,
        }
    }

    #[test]
    fn empty_whitelist_fails_closed_and_records_block() {
        let chain = GateChain::new();
        let result = chain.check(&GateRequest::new("read_file", "agent-a"));
        assert_eq!(result.decision, GateDecision::Block);
        assert!(!result.allowed);
        assert_eq!(result.steps[0].gate, "G1");
        assert_eq!(chain.ledger().len(), 1);
    }

    #[test]
    fn interactive_identity_skips_process_lookup_but_keeps_gates() {
        let chain = GateChain::new();
        chain.register_tools(["read_file"]);
        let mut request = GateRequest::new("read_file", "shell");
        request.interactive = true;
        let result = chain.check(&request);
        assert!(result.allowed);
        assert_eq!(result.steps[1].result, GateDecision::Pass);
        assert_eq!(result.steps[1].interactive, Some(true));
    }

    #[test]
    fn identity_ring_and_state_fail_closed() {
        let chain = GateChain::new();
        chain.register_tools(["read_file"]);
        let mut request = GateRequest::new("read_file", "agent-a");
        request.identity = Some(ready_identity(2, false));
        assert_eq!(chain.check(&request).decision, GateDecision::Block);
        request.identity = Some(GateIdentity {
            state: ProcessState::Stopped,
            ..ready_identity(1, true)
        });
        assert_eq!(chain.check(&request).decision, GateDecision::Block);
    }

    #[test]
    fn territory_frequency_and_high_danger_inputs_are_structured() {
        let chain = GateChain::new();
        chain.register_tools(["deploy"]);
        let mut request = GateRequest::new("deploy", "agent-a");
        request.identity = Some(ready_identity(1, true));
        request.target = "/project/foo.py".to_owned();
        request.territory = vec!["/project".to_owned()];
        request.timestamp = Some(100.0);
        let blocked = chain.check(&request);
        assert_eq!(blocked.decision, GateDecision::Block);
        assert_eq!(blocked.steps[3].gate, "G4");

        request.pre_approved = true;
        let allowed = chain.check(&request);
        assert!(allowed.allowed);
        assert_eq!(allowed.steps[2].risk_score, Some(5.5));
    }

    #[test]
    fn territory_matching_rejects_prefix_collisions() {
        let chain = GateChain::new();
        chain.register_tools(["read_file"]);
        let mut request = GateRequest::new("read_file", "agent-a");
        request.identity = Some(ready_identity(1, true));
        request.target = "/project/foo_secret/file.py".to_owned();
        request.territory = vec!["/project/foo".to_owned()];
        let result = chain.check(&request);
        assert_eq!(result.decision, GateDecision::Block);
        assert_eq!(result.steps[2].gate, "G3");
    }

    #[test]
    fn low_reputation_blocks_a_g3_frequency_warning() {
        let chain = GateChain::new();
        chain.register_tools(["read_file"]);
        for index in 0..10 {
            chain.ledger().record(GateLedgerEntry {
                agent_id: "agent-a".to_owned(),
                tool: "read_file".to_owned(),
                target: format!("/{index}"),
                result: GateDecision::Pass,
                timestamp: 90.0 + index as f64,
                pattern: "G1-PASS_G3-PASS".to_owned(),
            });
        }
        let mut request = GateRequest::new("read_file", "agent-a");
        request.identity = Some(ready_identity(1, true));
        request.reputation = Some(0.6);
        request.timestamp = Some(100.0);
        let result = chain.check(&request);
        assert_eq!(result.decision, GateDecision::Block);
        assert_eq!(
            result.steps.last().map(|step| step.result),
            Some(GateDecision::Block)
        );
    }

    #[test]
    fn bounded_ledger_recent_count_and_pattern_are_stable() {
        let ledger = GateLedger::with_capacity(2);
        for index in 0..3 {
            ledger.record(GateLedgerEntry {
                agent_id: "a".to_owned(),
                tool: "t".to_owned(),
                target: format!("/{index}"),
                result: GateDecision::Pass,
                timestamp: 100.0 + index as f64,
                pattern: "G1-PASS_G3-PASS".to_owned(),
            });
        }
        assert_eq!(ledger.len(), 2);
        assert_eq!(ledger.recent("a", "t", GATECHAIN_HISTORY_LIMIT).len(), 2);
        assert_eq!(ledger.count("a", "t", 102.0, 60.0), 2);
        ledger.clear();
        assert!(ledger.is_empty());
    }

    #[derive(Deserialize)]
    struct PolicyVector {
        kind: String,
        tools: Option<Vec<String>>,
        input: serde_json::Value,
        history_count: Option<usize>,
        expect: PolicyExpectation,
    }

    #[derive(Deserialize)]
    struct PolicyExpectation {
        allowed: bool,
        decision: String,
        blocked_gate: Option<String>,
    }

    #[test]
    fn shared_policy_vectors_match_gatechain_candidate() {
        let vectors: Vec<PolicyVector> = serde_json::from_str(include_str!(
            "../../../tests/fixtures/kernel_policy_vectors.json"
        ))
        .expect("policy fixture must be valid JSON");
        for vector in vectors
            .into_iter()
            .filter(|vector| vector.kind == "gatechain")
        {
            let chain = GateChain::new();
            chain.replace_tools(vector.tools.unwrap_or_default());
            let input: GateRequest = serde_json::from_value(vector.input).unwrap();
            for index in 0..vector.history_count.unwrap_or(0) {
                chain.ledger().record(GateLedgerEntry {
                    agent_id: input.agent_id.clone(),
                    tool: input.tool.clone(),
                    target: String::new(),
                    result: GateDecision::Pass,
                    timestamp: 90.0 + index as f64,
                    pattern: "G1-PASS_G3-PASS".to_owned(),
                });
            }
            let result = chain.check(&input);
            assert_eq!(result.allowed, vector.expect.allowed);
            assert_eq!(result.decision.as_str(), vector.expect.decision);
            if let Some(expected_gate) = vector.expect.blocked_gate {
                assert_eq!(
                    result
                        .steps
                        .iter()
                        .find(|step| step.result == GateDecision::Block)
                        .map(|step| step.gate.as_str()),
                    Some(expected_gate.as_str())
                );
            }
        }
    }
}
