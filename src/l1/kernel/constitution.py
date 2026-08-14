"""Constitution engine — parses .praxis-rules.md into runtime constraints.

All Agent actions must pass constitution.check() before execution.
No Agent can unilaterally modify anything without constitutional approval.

Enforcement chain:
  Agent tick() → constitution.check() → resource.check() → lock → execute
                                    ↓
                             block if violates rules

Also provides:
  - load/parse/render/save for .praxis-rules.md files
  - merge_proposal for Assembly Mode territory convergence
  - diff for comparing constitutions
  - BLANK_CONSTITUTION template for new projects

Implementation note: the built-in check evaluators and the descriptor
table live in ``constitution_checks.py``; the ``TerritoryConstitution``
dataclass and the territory file IO (parse/render/save/merge/diff) live
in ``constitution_io.py``.  This module composes them and re-exports the
public names so ``from l1.kernel.constitution import …`` keeps working.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from typing import Any

from .constitution_checks import (
    _BUILTIN_DESCRIPTORS,
    _CATCH_ALL,
    TAG_ACTION_MAP,
    CheckReport,
    _severity,
    set_metric_sink,
    set_posture_provider,
)
from .constitution_io import (
    _CONSTITUTION_FILE,
    BLANK_CONSTITUTION,
    CONSTITUTION_SOURCE_BLANK,
    TerritoryConstitution,
    diff_territory,
    load_territory,
    merge_proposal,
    parse_territory,
    render_territory,
    save_territory,
    update_territory,
)
from .params.agent import CONSTITUTION_CUSTOM_SECTION
from .rule_descriptor import CheckResult, RuleDescriptor, RuleSeverity

logger = logging.getLogger(__name__)

# Public surface — names imported from constitution_checks/constitution_io
# are re-exported here so ``from l1.kernel.constitution import …`` keeps
# working for existing callers (boot wiring, API handlers, tests).
__all__ = [
    "BLANK_CONSTITUTION",
    "CONSTITUTION_SOURCE_BLANK",
    "CheckReport",
    "Constitution",
    "TerritoryConstitution",
    "diff_territory",
    "get_constitution",
    "load_territory",
    "merge_proposal",
    "parse_territory",
    "render_territory",
    "reset_constitution",
    "save_territory",
    "set_metric_sink",
    "set_posture_provider",
    "update_territory",
]


# ═════════════════════════════════════════════════════════════════════════════
# Constitution engine (rule checking)
# ═════════════════════════════════════════════════════════════════════════════


class Constitution:
    """Constitution engine — the highest authority in the Agent OS.

    Rules can be hot-reloaded via reload() or updated at runtime via
    update_rules().  On BLOCK detection, emits NMI interrupt and
    EventBus signal for SSE broadcast to frontend.
    """

    def __init__(self):
        self._rules: list[RuleDescriptor] = list(_BUILTIN_DESCRIPTORS)
        self._lock = threading.Lock()
        self._constitution_path: str = ""
        self._cell_bus = None  # set by Cell to enable interrupt emission
        self._persist_handler: Callable[[list[dict], int], None] | None = None
        # Pre-computed index: action_category -> [rules] for fast check()
        self._action_index: dict[str, list[RuleDescriptor]] = {}
        self._catch_all_rules: list[RuleDescriptor] = []
        self._build_index()
        """Optional callback for persisting custom rules (set at boot to avoid L3 import)."""

    def set_persist_handler(self, handler: Callable[[list[dict], int], None]) -> None:
        """Register a callback to persist custom rules (called at boot from L3 wiring).

        Eliminates the ``from l3.config.settings_center import get_center``
        import from kernel layer.
        """
        self._persist_handler = handler

    # ── Cell bus binding (for constitution.violation NMI) ──

    def bind_cell(self, cell_bus: Any) -> None:
        """Bind a Cell bus so constitution violations trigger NMI interrupt.

        Called by Cell.__init__ after creating the cell bus.
        """
        self._cell_bus = cell_bus

    def _trigger_violation(self, action: str, agent_id: str, target: str, rule_id: str) -> None:
        """Emit constitution.violation NMI via cell bus."""
        if not self._cell_bus:
            return
        try:
            self._cell_bus.emit(
                "interrupt.triggered",
                {
                    "irq": "constitution.violation",
                    "data": {"action": action, "agent_id": agent_id, "target": target, "rule_id": rule_id},
                },
            )
        except Exception:
            logger.warning("constitution: cell bus emit failed — violation event lost")
        # Also emit EventBus signal for SSE broadcast
        try:
            from l1.kernel import get_event_bus  # lazy import avoids circular dep

            bus = get_event_bus()
            bus.emit_event(
                "constitution.violation",
                data={
                    "action": action,
                    "agent_id": agent_id,
                    "target": target,
                    "rule_id": rule_id,
                },
            )
        except Exception:
            logger.warning("constitution: event bus emit failed — violation event lost")

    # ── Rule index for fast check() ──────────────────────────────────────

    def _build_index(self) -> None:
        """Rebuild the action-category index from the current rule set.

        Rules with catch-all tags are placed in ``_catch_all_rules`` and
        evaluated for every action.  Rules with specific tags are indexed
        by action category (``file``, ``modify``, ``tool``, ``memory``,
        ``scout``, ``skill``) so ``check()`` only evaluates the relevant
        subset.
        """
        idx: dict[str, list[RuleDescriptor]] = {}
        catch_all: list[RuleDescriptor] = []
        for rule in self._rules:
            categories = TAG_ACTION_MAP.get(rule.tags, _CATCH_ALL)
            if _CATCH_ALL in categories:
                catch_all.append(rule)
            else:
                for cat in categories:
                    idx.setdefault(cat, []).append(rule)
        self._action_index = idx
        self._catch_all_rules = catch_all

    def _relevant_rules(self, action: str) -> list[RuleDescriptor]:
        """Return the subset of rules relevant to *action*.

        Combines catch-all rules (always evaluated) with rules indexed
        under the action's category.  The action category is derived
        from the action name heuristically.
        """
        category = self._action_category(action)
        specific = self._action_index.get(category, [])
        # No dedup needed: a rule is in EITHER catch-all OR specific, never both
        return list(self._catch_all_rules) + specific

    @staticmethod
    def _action_category(action: str) -> str:
        """Map an action name to its index category.

        Categories: ``file``, ``modify``, ``tool``, ``memory``,
        ``scout``, ``skill``.  Falls back to ``tool`` for unrecognised
        actions (conservative: evaluate all tool-related rules).
        """
        # File operations
        if action in ("read", "read_file", "grep", "grep_search", "glob", "ls", "search"):
            return "file"
        if action in (
            "write",
            "edit",
            "replace_string_in_file",
            "delete",
            "delete_file",
            "create",
            "create_file",
            "rename",
            "move",
            "patch",
            "format",
        ):
            return "modify"
        # Memory operations
        if action in (
            "memory_read",
            "memory_write",
            "memory_search",
            "memory_query",
            "memory_store",
            "memory_recall",
            "archive",
            "recall",
        ):
            return "memory"
        # Scout operations
        if action in ("scout", "scout_read", "scout_search", "investigate"):
            return "scout"
        # Skill operations
        if action in ("skill.use", "use_skill", "skill.load", "skill_list", "skill_use", "skill_load"):
            return "skill"
        # Default: all tool-related rules
        return "tool"

    # ── LLM-readable summary (injected into AgentLoop system prompt) ──

    def summary(self, for_agent: str = "") -> str:
        """Return a human-readable constitution summary for LLM context.

        Injected into AgentLoop's system prompt so the LLM knows
        the rules before making tool calls.  Filters rules relevant
        to the given agent if ``for_agent`` is provided.
        """
        with self._lock:
            must_rules = [r for r in self._rules if r.severity == RuleSeverity.MUST]
            should_rules = [r for r in self._rules if r.severity == RuleSeverity.SHOULD]

        lines = ["--- Constitution Rules ---"]
        lines.append("You MUST obey these rules. Violations will be blocked.")
        if must_rules:
            lines.append(f"\nMUST ({len(must_rules)} rules):")
            for r in must_rules:
                lines.append(f"  [{r.id}] {r.description}")
        if should_rules:
            lines.append(f"\nSHOULD ({len(should_rules)} rules):")
            for r in should_rules:
                lines.append(f"  [{r.id}] {r.description}")
        lines.append("\n--- End Constitution ---")
        return "\n".join(lines)

    # ── Hot-reload from file ──

    def load(self, path: str = "") -> dict:
        """Load constitution from .praxis-rules.md file."""
        if not path:
            path = _CONSTITUTION_FILE
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return {"success": False, "error": f"constitution not found: {path}"}

        custom_rules = self._parse_markdown(content)
        with self._lock:
            self._constitution_path = path
            self._rules = list(_BUILTIN_DESCRIPTORS) + custom_rules
            self._build_index()
        # Emit loaded event for SSE
        try:
            from l1.kernel import get_event_bus

            get_event_bus().emit_event(
                "constitution.loaded",
                data={
                    "rules": len(self._rules),
                    "custom": len(custom_rules),
                    "path": path,
                },
            )
        except Exception:
            logger.warning("constitution: failed to emit loaded event")
        return {"success": True, "rules": len(self._rules), "custom": len(custom_rules), "path": path}

    def reload(self) -> dict:
        """Reload constitution from the same file path (hot-reload)."""
        if not self._constitution_path:
            return {"success": False, "error": "no constitution path set"}
        return self.load(self._constitution_path)

    def update_rules(self, custom_rules: list[dict]) -> dict:
        """Add or update custom rules at runtime.

        Each rule dict:
          {"id": "...", "severity": "MUST|SHOULD|MAY",
           "description": "...", "section": "§custom"}

        Persists to SettingsCenter for L3 runtime overrides.
        """
        count = 0
        with self._lock:
            self._rules = [r for r in self._rules if r.source != "custom"]
            for spec in custom_rules:
                sev = _severity(spec.get("severity", "MUST"))
                self._rules.append(
                    RuleDescriptor(
                        id=spec.get("id", f"custom.{len(self._rules)}"),
                        section=spec.get("section", CONSTITUTION_CUSTOM_SECTION),
                        severity=sev,
                        description=spec.get("description", ""),
                        source="custom",
                    )
                )
                count += 1
        # Persist to SettingsCenter L3 (via registered callback, avoids direct import)
        if self._persist_handler:
            try:
                self._persist_handler(custom_rules, count)
            except Exception as e:
                logger.warning("constitution: persist handler failed: %s", e)
        else:
            logger.debug("constitution: no persist handler registered, custom rules not persisted")
        # Rebuild index after rule changes
        with self._lock:
            self._build_index()
        # Emit signal for SSE broadcast
        try:
            from l1.kernel import get_event_bus

            bus = get_event_bus()
            bus.emit_event("constitution.updated", data={"count": count})
        except Exception:
            logger.warning("constitution: failed to emit updated event")
        return {"success": True, "updated": count, "total": len(self._rules)}

    def clear_custom_rules(self) -> dict:
        """Remove all custom rules (keep built-in)."""
        with self._lock:
            self._rules = [r for r in self._rules if r.source != "custom"]
            self._build_index()
        return {"success": True, "total": len(self._rules)}

    def rules_list(self) -> list[dict]:
        """Return a summary dict for every loaded rule."""
        with self._lock:
            return [
                {
                    "id": r.id,
                    "section": r.section,
                    "severity": r.severity.name,
                    "description": r.description,
                    "source": r.source or "builtin",
                }
                for r in self._rules
            ]

    # ── Enhanced check with violation event emission ──

    def check(
        self, action: str, agent_id: str, target: str = "", territory: list[str] | None = None
    ) -> list[CheckReport]:
        """Evaluate relevant rules for an action and return non-pass reports.

        Uses the pre-computed action-category index to evaluate only rules
        whose tags match the action, reducing 17+ evaluations to ~5-8 per call.
        Catch-all rules (audit, L3, unmapped) are always evaluated.
        """
        reports: list[CheckReport] = []
        relevant = self._relevant_rules(action)
        for rule in relevant:
            result = self._evaluate(rule, action, agent_id, target, territory or [])
            if result == CheckResult.BLOCK:
                self._trigger_violation(action, agent_id, target, rule.id)
            if result != CheckResult.PASS:
                reports.append(
                    CheckReport(rule=rule, result=result, detail=self._describe(rule, action, agent_id, target))
                )
        return reports

    def is_allowed(self, action: str, agent_id: str, target: str = "", territory: list[str] | None = None) -> dict:
        """Check whether the action is allowed; return decision details."""
        reports = self.check(action, agent_id, target, territory)
        blocks = [r for r in reports if r.result == CheckResult.BLOCK]
        return {
            "allowed": len(blocks) == 0,
            "decision": "pass" if not blocks else "block",
            "blocks": len(blocks),
            "warns": len([r for r in reports if r.result == CheckResult.WARN]),
            "details": [
                {"section": r.rule.section, "rule_id": r.rule.id, "result": r.result.name, "detail": r.detail}
                for r in reports
            ],
        }

    def to_dict(self) -> dict:
        """Full constitution state for API export."""
        with self._lock:
            return {
                "path": self._constitution_path or "",
                "total_rules": len(self._rules),
                "builtin": len([r for r in self._rules if r.source != "custom"]),
                "custom": len([r for r in self._rules if r.source == "custom"]),
                "rules": [
                    {
                        "id": r.id,
                        "section": r.section,
                        "severity": r.severity.name,
                        "description": r.description,
                        "source": r.source or "builtin",
                    }
                    for r in self._rules
                ],
            }

    def _evaluate(self, rule, action, agent_id, target, territory) -> CheckResult:
        return rule.evaluate(action, agent_id, target, territory)

    def _describe(self, rule, action, agent_id, target) -> str:
        return f"{rule.section}: {rule.description} (action={action}, agent={agent_id}, target={target})"

    @staticmethod
    def _parse_markdown(content: str) -> list[RuleDescriptor]:
        rules: list[RuleDescriptor] = []
        current_section = ""
        for line in content.splitlines():
            m = re.match(r"^##+\s+(.+)$", line)
            if m:
                current_section = m.group(1).strip()
            sev = None
            if "[MUST]" in line:
                sev = RuleSeverity.MUST
            elif "[SHOULD]" in line:
                sev = RuleSeverity.SHOULD
            elif "[MAY]" in line:
                sev = RuleSeverity.MAY
            if sev:
                desc = re.sub(r"\[(MUST|SHOULD|MAY)\]", "", line).strip()
                if desc:
                    rules.append(
                        RuleDescriptor(
                            id=f"custom.{len(rules)}",
                            section=current_section or CONSTITUTION_CUSTOM_SECTION,
                            severity=sev,
                            description=desc,
                            source="custom",
                        )
                    )
        return rules


_constitution: Constitution | None = None
_constitution_lock = threading.Lock()


def get_constitution() -> Constitution:
    """Get the Constitution engine singleton."""
    global _constitution
    if _constitution is None:
        with _constitution_lock:
            if _constitution is None:
                _constitution = Constitution()
    return _constitution


def reset_constitution() -> None:
    """Reset the Constitution singleton for testing."""
    global _constitution
    _constitution = None
