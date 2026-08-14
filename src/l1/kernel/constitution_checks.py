"""Constitution checks — built-in rule check functions and descriptor table.

Extracted from constitution.py.  This module owns the ``_check_*``
evaluators, the posture/metric sink injection points, the ``CheckReport``
result type and the built-in ``RuleDescriptor`` table; the Constitution
engine (constitution.py) composes them and re-exports the public names so
``from l1.kernel.constitution import …`` keeps working.
"""

from __future__ import annotations

import logging
import os as _os
from collections.abc import Callable
from dataclasses import dataclass

from l1.kernel.discovery import get_config

from .params.agent import (
    CONSTITUTION_ACTION_LEN_THRESHOLD,
    CONSTITUTION_FILE_EXT,
    CONSTITUTION_GATE_ACTIONS,
    CONSTITUTION_KEYWORD,
    CONSTITUTION_SCOUT_AGENT_NAME,
    CONSTITUTION_SCOUT_BLOCKED,
    CONSTITUTION_SHARED_KEYWORD,
    SANDBOX_ROOT_PATH,
)
from .params.system import SKILL_POSTURE_OFFENSIVE
from .rule_descriptor import CheckResult, RuleDescriptor, RuleSeverity, str_to_severity
from .territory import is_within as _territory_is_within

logger = logging.getLogger(__name__)

# ── Tag constants for built-in descriptors ──
TAG_TERRITORY_WRITE = frozenset({"territory", "write"})
TAG_TERRITORY_READ = frozenset({"territory", "read"})
TAG_GATECHAIN = frozenset({"gatechain"})
TAG_GATECHAIN_CROSS = frozenset({"gatechain", "cross"})
TAG_SANDBOX = frozenset({"sandbox"})
TAG_SANDBOX_REVIEW = frozenset({"sandbox", "review"})
TAG_CONSTITUTION = frozenset({"constitution"})
TAG_AUDIT = frozenset({"audit"})
TAG_MEMORY = frozenset({"memory"})
TAG_TERRITORY_REVIEW = frozenset({"territory", "review"})
TAG_L3 = frozenset({"l3"})
TAG_SCOUT = frozenset({"scout"})
TAG_SCOUT_AUDIT = frozenset({"scout", "audit"})
TAG_MEMORY_RING = frozenset({"memory", "ring"})
TAG_SKILL = frozenset({"skill"})

# ── Tag-to-action-category map for pre-filtering ──
# Each entry maps a tag set to the action categories the rule applies to.
# "file" = file read/write/edit actions, "modify" = destructive actions,
# "tool" = any tool call, "memory" = memory operations, "scout" = scout ops,
# "skill" = skill operations, "all" = every action (catch-all).
# The Constitution engine uses this to build a pre-index that avoids
# evaluating irrelevant rules in check().
TAG_ACTION_MAP: dict[frozenset[str], frozenset[str]] = {
    TAG_TERRITORY_WRITE: frozenset({"file"}),
    TAG_TERRITORY_READ: frozenset({"file"}),
    TAG_GATECHAIN: frozenset({"tool"}),  # all tool calls
    TAG_GATECHAIN_CROSS: frozenset({"tool"}),  # all tool calls
    TAG_SANDBOX: frozenset({"modify"}),
    TAG_SANDBOX_REVIEW: frozenset({"modify"}),
    TAG_CONSTITUTION: frozenset({"modify"}),  # only modify/constitution-related actions
    TAG_AUDIT: frozenset({"all"}),  # always evaluated
    TAG_TERRITORY_REVIEW: frozenset({"file"}),  # cross-territory changes
    TAG_L3: frozenset({"all"}),  # always evaluated
    TAG_SCOUT: frozenset({"scout"}),
    TAG_SCOUT_AUDIT: frozenset({"scout"}),
    TAG_MEMORY: frozenset({"memory"}),
    TAG_MEMORY_RING: frozenset({"memory"}),
    TAG_SKILL: frozenset({"skill"}),
}
# Catch-all: rules with empty tags or unmapped tags go to "all"
_CATCH_ALL = frozenset({"all"})


@dataclass
class CheckReport:
    """Result of evaluating a single rule against an action."""

    rule: RuleDescriptor
    result: CheckResult
    detail: str = ""


def _severity(s: str) -> RuleSeverity:
    return str_to_severity(s)


# ── Built-in check functions ──


def _check_territory(
    rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]
) -> CheckResult:
    ca = get_config("constitution")
    if ca:
        file_actions = frozenset(ca.get("file_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_FILE_ACTIONS

        file_actions = CONSTITUTION_FILE_ACTIONS
    if action not in file_actions or not target:
        return CheckResult.PASS
    if territory and not _territory_is_within(target, territory):
        return CheckResult.BLOCK if rule.severity == RuleSeverity.MUST else CheckResult.WARN
    return CheckResult.PASS


def _check_sandbox(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    ca = get_config("constitution")
    if ca:
        modify_actions = frozenset(ca.get("modify_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_MODIFY_ACTIONS

        modify_actions = CONSTITUTION_MODIFY_ACTIONS
    if action in modify_actions:
        if rule.severity == RuleSeverity.MUST and target:
            # Real path check: verify target starts with configured sandbox root
            abs_target = _os.path.abspath(target)
            return CheckResult.PASS if _territory_is_within(abs_target, [SANDBOX_ROOT_PATH]) else CheckResult.WARN
        return CheckResult.PASS
    return CheckResult.PASS


def _check_constitution_mod(
    rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]
) -> CheckResult:
    if not target:
        return CheckResult.PASS
    if CONSTITUTION_KEYWORD in target.lower():
        return CheckResult.BLOCK
    if target.endswith(CONSTITUTION_FILE_EXT):
        return CheckResult.BLOCK
    return CheckResult.PASS


def _check_gate(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    """G1 gate — tool whitelist check. Returns WARN (not BLOCK) for high-risk actions
    because GateChain G5 makes the final authorization decision based on reputation,
    history, and context. G1 only flags, it does not block."""
    ca = get_config("constitution")
    if ca:
        modify_actions = frozenset(ca.get("modify_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_MODIFY_ACTIONS

        modify_actions = CONSTITUTION_MODIFY_ACTIONS
    if action in CONSTITUTION_GATE_ACTIONS:
        return CheckResult.WARN
    return (
        CheckResult.WARN
        if action in modify_actions and len(action) > CONSTITUTION_ACTION_LEN_THRESHOLD
        else CheckResult.PASS
    )


def _check_scout(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    ca = get_config("constitution")
    if ca:
        file_actions = frozenset(ca.get("file_actions", []))
    else:
        from l1.kernel.params.agent import CONSTITUTION_FILE_ACTIONS

        file_actions = CONSTITUTION_FILE_ACTIONS
    if agent_id == CONSTITUTION_SCOUT_AGENT_NAME:
        if action in CONSTITUTION_SCOUT_BLOCKED:
            return CheckResult.BLOCK
        if action in file_actions:
            return CheckResult.PASS
    return CheckResult.PASS


def _check_audit(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    return CheckResult.PASS


# Posture provider — injected at boot by L3 wiring (kernel never imports L3).
# Returns the ``get_posture()`` dict {security_mode, harness_mode,
# classification, full_power, ...} or None when not wired.
_posture_provider: Callable[[], dict | None] | None = None
# Metric sink — injected at boot by L3 wiring (kernel never imports L3).
# Receives (name, value, tags); None when not wired (backward compatible).
_metric_sink: Callable[[str, float, dict | None], None] | None = None


def set_metric_sink(sink: Callable[[str, float, dict | None], None] | None) -> None:
    """Register the metric sink callback (called at boot from L3 wiring).

    Eliminates the ``from l3.services.stats_center import get_center`` import
    from the kernel layer — the sink is injected, not imported. Used by the
    §9.2 posture gate to record BLOCK decisions as security.* counters.
    """
    global _metric_sink
    _metric_sink = sink


def set_posture_provider(provider: Callable[[], dict | None] | None) -> None:
    """Register the posture provider callback (called at boot from L3 wiring).

    Eliminates the ``from l3.tool_system.security_mode import get_posture``
    import from the kernel layer — the provider is injected, not imported.
    """
    global _posture_provider
    _posture_provider = provider


def _check_skill_posture(
    rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]
) -> CheckResult:
    """Constitutional gate: offensive-posture skills require attack posture.

    Applies to ``skill.use`` (session catalog) AND ``use_skill`` (the actual
    tool-pipeline action name) — an offensive skill is BLOCKED unless the
    injected posture provider reports full_power (attack classification +
    detection-bypass confirmed). ``skill.load`` (registration) is not blocked:
    offensive skills may exist in the registry but stay unusable — posture
    gating happens at use/injection. When no provider is wired, the rule
    passes (backward compatible).
    """
    if action not in ("skill.use", "use_skill"):
        return CheckResult.PASS
    provider = _posture_provider
    if provider is None:
        return CheckResult.PASS
    try:
        posture = provider() or {}
    except Exception:
        return CheckResult.PASS
    if posture.get("full_power"):
        return CheckResult.PASS
    # Not full power: block use of offensive-posture skills.
    try:
        from l1.kernel.skill import get_skill_manager

        skill = get_skill_manager().get(target)
        if skill and skill.get("posture") == SKILL_POSTURE_OFFENSIVE:
            sink = _metric_sink
            if sink is not None:
                from contextlib import suppress

                with suppress(Exception):
                    sink("security.gate.skill_use.blocked", 1.0, {"target": target})
            return CheckResult.BLOCK
    except Exception:
        pass
    return CheckResult.PASS


def _check_cross(rule: RuleDescriptor, action: str, agent_id: str, target: str, territory: list[str]) -> CheckResult:
    if action in CONSTITUTION_SCOUT_BLOCKED:
        if territory and any(CONSTITUTION_SHARED_KEYWORD in t.lower() for t in territory):
            return CheckResult.BLOCK
        return CheckResult.WARN
    return CheckResult.PASS


_BUILTIN_DESCRIPTORS: list[RuleDescriptor] = [
    RuleDescriptor(
        id="territory.write",
        section="§2.3",
        severity=RuleSeverity.MUST,
        description="Agent must not write outside its territory",
        check_fn=_check_territory,
        tags=TAG_TERRITORY_WRITE,
    ),
    RuleDescriptor(
        id="territory.read_l3",
        section="§3.1",
        severity=RuleSeverity.MUST,
        description="Agent must not read files outside its territory without L3 approval",
        check_fn=_check_territory,
        tags=TAG_TERRITORY_READ,
    ),
    RuleDescriptor(
        id="gatechain.all",
        section="§3.3",
        severity=RuleSeverity.MUST,
        description="All tool calls must pass GateChain G1-G5",
        check_fn=_check_gate,
        tags=TAG_GATECHAIN,
    ),
    RuleDescriptor(
        id="gatechain.cross",
        section="§3.4",
        severity=RuleSeverity.MUST,
        description="Cross-unit tool calls require G5 approval",
        check_fn=_check_gate,
        tags=TAG_GATECHAIN_CROSS,
    ),
    RuleDescriptor(
        id="sandbox.writes",
        section="§4.5",
        severity=RuleSeverity.MUST,
        description="All modifications must go through sandbox (no direct writes)",
        check_fn=_check_sandbox,
        tags=TAG_SANDBOX,
    ),
    RuleDescriptor(
        id="sandbox.review",
        section="§4.6",
        severity=RuleSeverity.MUST,
        description="All modifications must be reviewable by L3 before flush",
        check_fn=_check_sandbox,
        tags=TAG_SANDBOX_REVIEW,
    ),
    RuleDescriptor(
        id="constitution.modify",
        section="§4.7",
        severity=RuleSeverity.MUST,
        description="No Agent may modify the constitution itself",
        check_fn=_check_constitution_mod,
        tags=TAG_CONSTITUTION,
    ),
    RuleDescriptor(
        id="audit.trail",
        section="§5.1",
        severity=RuleSeverity.MUST,
        description="All tool calls must be logged with audit trail",
        check_fn=_check_audit,
        tags=TAG_AUDIT,
    ),
    RuleDescriptor(
        id="decision.memory",
        section="§5.2",
        severity=RuleSeverity.SHOULD,
        description="All decisions must be recorded in memory Ring 2",
        check_fn=None,
        tags=TAG_MEMORY,
    ),
    RuleDescriptor(
        id="territory.cross_review",
        section="§6.1",
        severity=RuleSeverity.MUST,
        description="Cross-territory changes require peer review",
        check_fn=_check_cross,
        tags=TAG_TERRITORY_REVIEW,
    ),
    RuleDescriptor(
        id="l3.arbiter",
        section="§6.2",
        severity=RuleSeverity.MUST,
        description="L3 is the final arbiter of all disputes",
        check_fn=None,
        tags=TAG_L3,
    ),
    RuleDescriptor(
        id="scout.readonly",
        section="§7.1",
        severity=RuleSeverity.MUST,
        description="Scouts are read-only and depth=1",
        check_fn=_check_scout,
        tags=TAG_SCOUT,
    ),
    RuleDescriptor(
        id="scout.log",
        section="§7.2",
        severity=RuleSeverity.SHOULD,
        description="Scout findings must be logged before disposal",
        check_fn=_check_scout,
        tags=TAG_SCOUT_AUDIT,
    ),
    RuleDescriptor(
        id="ring.context",
        section="§8.1",
        severity=RuleSeverity.MUST,
        description="Agent context must be built from Ring memory, not raw output",
        check_fn=None,
        tags=TAG_MEMORY_RING,
    ),
    RuleDescriptor(
        id="ring.persist",
        section="§8.2",
        severity=RuleSeverity.SHOULD,
        description="Important decisions must be persisted to Ring 3 (long-term)",
        check_fn=None,
        tags=TAG_MEMORY_RING,
    ),
    RuleDescriptor(
        id="skill.builtin_readonly",
        section="§9.1",
        severity=RuleSeverity.MUST,
        description="Built-in (shipped) skills are read-only — no agent may modify or delete them",
        check_fn=None,
        tags=TAG_SKILL,
    ),
    RuleDescriptor(
        id="skill.offensive_posture",
        section="§9.2",
        severity=RuleSeverity.MUST,
        description="Offensive-posture skills require attack posture (full_power) for use",
        check_fn=_check_skill_posture,
        tags=TAG_SKILL,
    ),
]
