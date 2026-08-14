"""CiReview — shared constants, helpers and report model.

Extracted from ``ci_review.py``: the settings-key whitelist vocabulary, the
key-validation helpers and the CardCiReport dataclass. The service class
stays in ``ci_review.py`` (facade).
"""

from __future__ import annotations

import fnmatch
import re
import time
from dataclasses import dataclass, field

# Functional setting suffixes (without the ci.review. prefix).  Business
# surfaces (API / L2 Shell) may mutate these globally or per scope
# (cell / agent).  Control-plane keys (ci.control.*) are writable too but
# require an explicit admin confirmation (see _is_control_key).
CI_SETTING_SUFFIXES: frozenset[str] = frozenset(
    {
        "enabled",
        "auto_trigger",
        "llm_review",
        "gates",
        "escalate_reject",
        "route_convention",
        "reputation",
        "lean_trace",
        "todo_linkage",
        "notify.enabled",
    }
)

# Back-compat alias: the full ci.review.* key set derived from suffixes.
CI_SETTING_KEYS: frozenset[str] = frozenset(f"ci.review.{s}" for s in CI_SETTING_SUFFIXES)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_control_key(key: str) -> bool:
    """True for control-plane keys (ci.control.*) — API-writable with admin."""
    return key in ("ci.control.api.writable", "ci.control.shell.writable")


def _is_allowed_key(key: str) -> bool:
    """Check a settings key against the dynamic whitelist.

    Accepts ``ci.review.<suffix>``, ``ci.review.cell.<id>.<suffix>`` and
    ``ci.review.agent.<id>.<suffix>`` (ids must match ``[A-Za-z0-9_-]+``),
    plus control-plane keys (handled separately with admin confirmation).
    """
    if _is_control_key(key):
        return True
    if not key.startswith("ci.review."):
        return False
    rest = key[len("ci.review.") :]
    parts = rest.split(".")
    if len(parts) == 1:
        return parts[0] in CI_SETTING_SUFFIXES
    if len(parts) >= 3 and parts[0] in ("cell", "agent") and ".".join(parts[2:]) in CI_SETTING_SUFFIXES:
        return bool(_ID_PATTERN.match(parts[1]))
    return False


def _normalize_key(key: str) -> str:
    """Map a short alias (e.g. ``enabled``) to its full ``ci.review.*`` key."""
    if key.startswith("ci."):
        return key
    return f"ci.review.{key}" if key in CI_SETTING_SUFFIXES else key


def _match_any(path: str, patterns: list[str]) -> bool:
    """True when *path* matches any glob pattern (case-insensitive fnmatch)."""
    lowered = path.lower()
    return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)


@dataclass
class CardCiReport:
    """One CI review result bound to a completed card."""

    card_id: str
    run_id: str
    state: str  # completed / failed / cancelled
    verdict: str  # PASS / NEEDS_CHANGES / REJECT / SKIPPED
    agent_id: str = ""
    gates: list[dict] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    review: dict = field(default_factory=dict)
    archive_ref: str = ""
    error: str = ""
    context: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for persistence."""
        return {
            "card_id": self.card_id,
            "run_id": self.run_id,
            "state": self.state,
            "verdict": self.verdict,
            "agent_id": self.agent_id,
            "gates": self.gates,
            "changed_files": self.changed_files,
            "review": self.review,
            "archive_ref": self.archive_ref,
            "error": self.error,
            "context": self.context,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
