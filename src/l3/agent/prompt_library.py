"""Cell-domain shared system-prompt library (3.2) — two-layer Cell prompt pool.

The execution layer of a Cell runs 3 Peer Agent terminals (A/B/C); their
system prompts previously came from scattered built-in templates. This
library gives the Cell a unified, layered prompt pool:

  - Upper layer (shared base): the Cell-wide static base prompt shared by
    all 3 AgentLoop sessions (configured text, e.g. the per-Cell Agents
    handbook / department brief).
  - Lower layer (dynamic base): per-Agent.Cell-doc prompts (keyed by
    ``Agent-{cell_id}.md``), injected automatically by the system — the
    injected text is picked by context pressure and card dispatch, and
    initialized on Cell boot.

Both layers are config-driven (``Cell-{cell_id}-Agents.md`` / config
text), enabled by default, operator-gated (API ``/api/v2/memory/prompt-
library`` + L2 ``/memory prompt-library``), and read-only for users
(overrides come from the system, not from user edits).

Degrades gracefully: a disabled library, an absent Cell doc, or a missing
layer all return empty text and never raise.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.system import PROMPT_LIBRARY_ENABLED_DEFAULT, PROMPT_LIBRARY_PRESSURE_HIGH

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": PROMPT_LIBRARY_ENABLED_DEFAULT}
_lock = threading.RLock()

# Upper layer: cell_id -> shared base prompt (all 3 AgentLoop sessions).
_shared_base: dict[str, str] = {}
# Lower layer: (cell_id, doc_key) -> dynamic prompt (Agent.Cell docs).
_dynamic_docs: dict[tuple[str, str], str] = {}


def prompt_library_status() -> dict:
    """Return the Cell prompt-library switch state."""
    with _lock:
        return {"enabled": bool(_state["enabled"])}


def set_prompt_library_switches(enabled: bool | None = None) -> dict:
    """Set the prompt-library operator switch.

    Args:
        enabled: master switch (None = keep current).

    Returns:
        dict with success flag and the effective switch.
    """
    with _lock:
        if enabled is not None:
            _state["enabled"] = bool(enabled)
        return {"success": True, **prompt_library_status()}


def reset_prompt_library() -> None:
    """Reset the library (switches + all layers) for tests / lifecycle."""
    with _lock:
        _state["enabled"] = PROMPT_LIBRARY_ENABLED_DEFAULT
        _shared_base.clear()
        _dynamic_docs.clear()


def set_shared_base(cell_id: str, text: str, source: str = "system") -> bool:
    """Set the Cell's upper-layer shared base prompt (3 AgentLoop sessions).

    Read-only guard: the prompt-library text is SYSTEM-managed — only a
    ``source="system"`` caller may write; user edits are forbidden.

    Args:
        cell_id: the Cell to set.
        text: the shared base prompt text.
        source: caller identity ("system" allowed; anything else rejected).

    Returns:
        True when written, False when rejected (user source / empty).
    """
    if source != "system":
        logger.debug("prompt_library: user write rejected (system-managed)")
        return False
    if not cell_id:
        return False
    with _lock:
        _shared_base[cell_id] = text
        return True


def get_shared_base(cell_id: str) -> str:
    """Return the Cell's shared base prompt (upper layer)."""
    with _lock:
        return _shared_base.get(cell_id, "")


def set_dynamic_doc(cell_id: str, doc_key: str, text: str, source: str = "system") -> bool:
    """Set a lower-layer dynamic prompt (Agent.Cell doc, keyed by doc_key).

    Read-only guard: only a ``source="system"`` caller may write; user
    edits are forbidden (system-managed library).

    Args:
        cell_id: the owning Cell.
        doc_key: the Agent.Cell doc key (e.g. ``Agent-{cell_id}.md``).
        text: the dynamic prompt text.
        source: caller identity ("system" allowed; anything else rejected).

    Returns:
        True when written, False when rejected (user source / empty).
    """
    if source != "system":
        logger.debug("prompt_library: user write rejected (system-managed)")
        return False
    if not cell_id or not doc_key:
        return False
    with _lock:
        _dynamic_docs[(cell_id, doc_key)] = text
        return True


def get_dynamic_doc(cell_id: str, doc_key: str) -> str:
    """Return a lower-layer dynamic prompt ("" when absent)."""
    with _lock:
        return _dynamic_docs.get((cell_id, doc_key), "")


def resolve_cell_prompt(cell_id: str, pressure: float = 0.0) -> str:
    """Resolve the Cell's layered prompt for injection (auto-hit by pressure).

    Upper layer (shared base) is always injected when present. The lower
    layer (dynamic docs) is hit automatically: under high context pressure
    (>= PROMPT_LIBRARY_PRESSURE_HIGH) the dynamic doc is appended so the
    peer agent keeps the Cell's program visible; otherwise the shared base
    alone is used (initialization injection).

    Args:
        cell_id: the producing Cell.
        pressure: current context pressure ratio (0..1+).

    Returns:
        The combined prompt text (shared base + dynamic doc on high
        pressure). Empty when the library is disabled or nothing set.
    """
    with _lock:
        enabled = bool(_state["enabled"])
        base = _shared_base.get(cell_id, "")
        if not enabled:
            return ""
    # Auto-hit: under high pressure, append the Cell's dynamic doc.
    if pressure >= PROMPT_LIBRARY_PRESSURE_HIGH:
        doc_key = f"Agent-{cell_id}.md"
        dynamic = get_dynamic_doc(cell_id, doc_key)
        if dynamic:
            return (base + "\n\n" + dynamic) if base else dynamic
    return base
