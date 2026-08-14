"""Global shared system-prompt library (3.2, P0-③) — cross-Cell prompt pools.

Manages the global shared system prompts every Cell builds on (the
"Cell upper-layer base"): the library is split into sub-libraries so a
Cell can selectively load what it needs — e.g. security, performance
optimization, extension. Selection is driven by the system (task load and
L3A dynamic load), not by the user.

Sub-library text is config-driven: each sub-library is loaded from
``config/prompts/<sub>.md`` (registered at boot / on first use) and
overridable via ``config/praxis.yaml`` ``prompts:`` (system-managed; user
edits are forbidden).

Degrades gracefully: a disabled library, an unknown sub-library, or a
missing config file all return empty text and never raise.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from l1.kernel.params.system import (
    GLOBAL_PROMPT_LIBRARY_ENABLED_DEFAULT,
    GLOBAL_PROMPT_LOAD_HIGH,
    GLOBAL_PROMPT_LOAD_MEDIUM,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": GLOBAL_PROMPT_LIBRARY_ENABLED_DEFAULT}
_lock = threading.RLock()

# Sub-library registry: name -> prompt text (security / performance / extension / ...).
_sub_libraries: dict[str, str] = {}
_loaded: set[str] = set()


def global_prompt_library_status() -> dict:
    """Return the global prompt-library switch state + registered sub-libs."""
    with _lock:
        return {
            "enabled": bool(_state["enabled"]),
            "sub_libraries": sorted(_sub_libraries.keys()),
        }


def set_global_prompt_library_switches(enabled: bool | None = None) -> dict:
    """Set the global prompt-library operator switch.

    Args:
        enabled: master switch (None = keep current).

    Returns:
        dict with success flag and the effective state.
    """
    with _lock:
        if enabled is not None:
            _state["enabled"] = bool(enabled)
        return {"success": True, **global_prompt_library_status()}


def reset_global_prompt_library() -> None:
    """Reset the library (switches + sub-library registry) for tests."""
    with _lock:
        _state["enabled"] = GLOBAL_PROMPT_LIBRARY_ENABLED_DEFAULT
        _sub_libraries.clear()
        _loaded.clear()


def _config_dir() -> Path:
    """Locate the config/prompts directory (repo root, best-effort)."""
    try:
        from l1.kernel.paths import get_paths

        root = get_paths().root
        return Path(root) / "config" / "prompts"
    except Exception:
        return Path("config") / "prompts"


def _load_sub_library(name: str) -> str:
    """Load a sub-library from config/prompts/<name>.md (once)."""
    with _lock:
        if name in _loaded:
            return _sub_libraries.get(name, "")
    path = _config_dir() / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.debug("global_prompt_library: no config/prompts/%s.md", name)
        text = ""
    with _lock:
        if text:
            _sub_libraries[name] = text
        _loaded.add(name)
        return text


def register_sub_library(name: str, text: str, source: str = "system") -> bool:
    """Register a sub-library (config-driven text, system-managed).

    Read-only guard: the global prompt-library text is SYSTEM-managed —
    only a ``source="system"`` caller may register a sub-library; user
    edits are forbidden.

    Args:
        name: sub-library name (e.g. security / performance / extension).
        text: the sub-library prompt text.
        source: caller identity ("system" allowed; anything else rejected).

    Returns:
        True when registered, False when rejected (user source / empty).
    """
    if source != "system":
        logger.debug("global_prompt_library: user write rejected (system-managed)")
        return False
    if not name or not text:
        return False
    with _lock:
        _sub_libraries[name] = text
        _loaded.add(name)
        return True


def list_sub_libraries() -> list[str]:
    """Return the names of all known sub-libraries."""
    with _lock:
        return sorted(_sub_libraries.keys())


def resolve_global_prompt(load: float = 0.0, domain: str = "") -> str:
    """Resolve the global prompt for a Cell by system load + domain.

    Selection is driven by the system: under high load the performance
    sub-library leads (efficient execution); a security-related domain
    adds the security sub-library; the extension sub-library is the
    general baseline. Enabled by default; disabled → empty.

    Args:
        load: current system/L3A load ratio (0..1+).
        domain: optional card/task domain hint.

    Returns:
        The combined global prompt text (empty when disabled).
    """
    with _lock:
        enabled = bool(_state["enabled"])
        known = set(_sub_libraries.keys())
    if not enabled:
        return ""
    # Config-driven loading: ensure the built-in sub-libraries are loaded
    # from config/prompts/<name>.md (lazy, once); layered-key fallback
    # (global.<name>) applies when the config file is absent.
    for name in ("security", "performance", "extension"):
        if name not in known:
            text = _load_sub_library(name)
            if not text:
                try:
                    from l1.kernel.prompts import get_prompt

                    text = get_prompt(f"global.{name}", "")
                except Exception:
                    text = ""
            if text:
                with _lock:
                    _sub_libraries[name] = text
                    known.add(name)
    # System-driven selection (never user choice).
    order: list[str] = []
    if (
        load >= GLOBAL_PROMPT_LOAD_HIGH
        and "performance" in known
        or load >= GLOBAL_PROMPT_LOAD_MEDIUM
        and "performance" in known
    ):
        order.append("performance")
    if "security" in known and (domain and any(k in domain.lower() for k in ("security", "safety", "attack"))):
        order.append("security")
    if "extension" in known:
        order.append("extension")
    parts = [_sub_libraries[n] for n in order if _sub_libraries.get(n)]
    return "\n\n".join(parts)
