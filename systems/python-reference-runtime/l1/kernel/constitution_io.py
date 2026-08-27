"""Constitution IO — territory constitution dataclass and file parsing.

Extracted from constitution.py.  This module owns ``TerritoryConstitution``,
the blank template, and the parse/render/save/merge/diff functions for
``.praxis-rules.md`` territory files; the Constitution engine
(constitution.py) composes them and re-exports the public names.
"""

from __future__ import annotations

import logging
import os as _os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .params.agent import CONSTITUTION_DEFAULT_PATH, CONSTITUTION_ENV_VAR, REP_DEFAULT_REPUTATION
from .params.system import DEFAULT_TOKEN_BUDGET

logger = logging.getLogger(__name__)

# Configurable constitution path — env var override
_CONSTITUTION_FILE = _os.environ.get(CONSTITUTION_ENV_VAR, CONSTITUTION_DEFAULT_PATH)

CONSTITUTION_SOURCE_BLANK = "blank"

BLANK_CONSTITUTION = """# NOMOS Constitution
# Version: 1
# Territory definitions — empty, to be decided by Assembly Mode
# Format: agent_id: territory1, territory2, territory3

# GateChain rules
G1: workspace_fingerprint  # Tool whitelist
G2: identity_verification  # Identity verification
G3: permission_check       # Permission check
G4: compliance_scan        # Compliance scan
G5: report_decision        # Witness decision

# Defaults
default_reputation: 0.85
token_budget: 73000
"""


@dataclass
class TerritoryConstitution:
    """Lightweight constitution data for territory management."""

    territories: dict[str, list[str]] = field(default_factory=dict)
    gate_rules: dict[str, str] = field(default_factory=dict)
    default_reputation: float = REP_DEFAULT_REPUTATION
    token_budget: int = DEFAULT_TOKEN_BUDGET
    version: int = 1
    source: str = ""

    def is_blank(self) -> bool:
        """Return True if no territories are defined."""
        return not self.territories


def load_territory(path: str = "") -> TerritoryConstitution:
    """Load territory constitution from file. Returns blank if not found."""
    if not path:
        path = _CONSTITUTION_FILE
    p = Path(path)
    if not p.exists():
        return TerritoryConstitution(source=CONSTITUTION_SOURCE_BLANK)
    return parse_territory(p.read_text(encoding="utf-8"), source=str(p))


# ── Scalar key setters (registration-style; extend by adding to _KEY_SETTERS) ──


def _set_default_reputation(c: TerritoryConstitution, value: str) -> None:
    """Parse the default_reputation scalar (float, 0..1)."""
    try:
        c.default_reputation = float(value)
    except Exception:
        logger.warning("constitution: invalid default_reputation: %s", value)


def _set_token_budget(c: TerritoryConstitution, value: str) -> None:
    """Parse the token_budget scalar (int)."""
    try:
        c.token_budget = int(value)
    except Exception:
        logger.warning("constitution: invalid token_budget: %s", value)


def _set_version(c: TerritoryConstitution, value: str) -> None:
    """Parse the version scalar (int)."""
    try:
        c.version = int(value)
    except Exception:
        logger.warning("constitution: invalid version: %s", value)


# Exact-key setters — registration-style dispatch (dict lookup, no elif chain).
_KEY_SETTERS: dict[str, Callable[[TerritoryConstitution, str], None]] = {
    "default_reputation": _set_default_reputation,
    "token_budget": _set_token_budget,
    "version": _set_version,
}


def parse_territory(text: str, source: str = "") -> TerritoryConstitution:
    """Parse territory constitution text into a TerritoryConstitution."""
    c = TerritoryConstitution(source=source)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key.startswith("agent_"):
            c.territories[key] = [t.strip() for t in value.split(",") if t.strip()]
        elif key.startswith("G") and len(key) <= 3:
            c.gate_rules[key] = value
        else:
            setter = _KEY_SETTERS.get(key)
            if setter:
                setter(c, value)
    return c


def render_territory(c: TerritoryConstitution) -> str:
    """Render a TerritoryConstitution back to markdown text."""
    lines = ["# NOMOS Constitution", f"# Version: {c.version}", ""]
    lines.append("# Territory definitions")
    for agent_id, territories in c.territories.items():
        lines.append(f"{agent_id}: {', '.join(territories)}")
    lines.append("")
    lines.append("# GateChain rules")
    for gate, desc in c.gate_rules.items():
        lines.append(f"{gate}: {desc}")
    lines.append("")
    lines.append("# Defaults")
    lines.append(f"default_reputation: {c.default_reputation}")
    lines.append(f"token_budget: {c.token_budget}")
    return "\n".join(lines) + "\n"


def save_territory(c: TerritoryConstitution, path: str = "") -> dict:
    """Save territory constitution to file."""
    if not path:
        path = _CONSTITUTION_FILE
    try:
        Path(path).write_text(render_territory(c), encoding="utf-8")
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_territory(c: TerritoryConstitution, agent_id: str, new_territories: list[str]) -> dict:
    """Update a single agent's territory."""
    c.territories[agent_id] = new_territories
    c.version += 1
    return {"success": True, "agent_id": agent_id, "territories": new_territories, "version": c.version}


def merge_proposal(c: TerritoryConstitution, proposal: dict) -> dict:
    """Merge a proposal from Assembly Mode into the constitution."""
    for agent_id, territories in proposal.items():
        if agent_id.startswith("agent_"):
            c.territories[agent_id] = territories
    c.version += 1
    save_territory(c)
    return {"success": True, "agents": list(proposal.keys()), "version": c.version}


def diff_territory(old: TerritoryConstitution, new: TerritoryConstitution) -> dict:
    """Compare two territory constitutions and return differences."""
    changes = {}
    for agent_id in set(list(old.territories.keys()) + list(new.territories.keys())):
        old_t = set(old.territories.get(agent_id, []))
        new_t = set(new.territories.get(agent_id, []))
        added = new_t - old_t
        removed = old_t - new_t
        if added or removed:
            changes[agent_id] = {"added": list(added), "removed": list(removed)}
    return {"changed": len(changes) > 0, "changes": changes}
