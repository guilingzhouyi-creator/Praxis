"""Premise guard — post-compaction anchor audit for the decision layer.

After a session/memory compression pass folds away history, the premise
guard re-checks that high-value anchors — user intents, constraints,
convention references — survived inside the summary. Anchors are extracted
before the fold (fingerprinted by content); after folding, anchors missing
from the summary produce a one-shot reminder injected into the folded
context so a lost premise is surfaced instead of silently dropped.

The guard is deterministic, side-channel safe and never raises: every
failure path returns an empty reminder set and leaves the summary intact.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any

from l1.kernel.params.system import (
    LOG_TRUNC_120,
    PREMISE_GUARD_ENABLED_DEFAULT,
    PREMISE_GUARD_MAX_ANCHORS,
    PREMISE_GUARD_MIN_ANCHOR_CHARS,
    PREMISE_GUARD_REMINDER_LIMIT,
)

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": PREMISE_GUARD_ENABLED_DEFAULT}
_lock = threading.RLock()

# Constraint/intent anchor signals — lines that carry premises the
# decision layer must not lose across a fold.
_ANCHOR_RE = re.compile(
    r"\b(?:must|never|always|constraint|constraints|requirement|requirements|decided|decision|approved|rejected|"
    r"intent|goal|objective|because|note|important|convention|rule)\b[^\n]{0,160}",
    re.I,
)
_FILLER_RE = re.compile(r"^(?:ok|okay|yes|no|sure|great|good|thanks|thank you|got it|understood)[.!?]?$", re.I)


def premise_guard_status() -> dict:
    """Return the guard operator state."""
    with _lock:
        return {"enabled": bool(_state["enabled"])}


def set_premise_guard(enabled: bool | None = None) -> dict:
    """Set the premise-guard master switch.

    Args:
        enabled: None keeps the current state.

    Returns:
        dict with success flag and the effective switch.
    """
    with _lock:
        if enabled is not None:
            _state["enabled"] = bool(enabled)
    return {"success": True, **premise_guard_status()}


def reset_premise_guard() -> None:
    """Reset the guard switch (tests / lifecycle)."""
    with _lock:
        _state["enabled"] = PREMISE_GUARD_ENABLED_DEFAULT


def _fingerprint(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def extract_anchors(messages: list) -> list[dict]:
    """Collect high-value anchors from pre-fold messages.

    Args:
        messages: session/memory entries with ``content`` (str) and a
            ``role``/``entry_type`` hint.

    Returns:
        list of {"text", "role", "fingerprint"} — capped at
        PREMISE_GUARD_MAX_ANCHORS.
    """
    anchors: list[dict] = []
    for m in messages or []:
        content = ""
        role = ""
        if isinstance(m, dict):
            content = str(m.get("content", "") or "")
            role = str(m.get("role", m.get("entry_type", "")) or "")
        else:
            content = str(getattr(m, "content", "") or "")
            role = str(getattr(m, "role", getattr(m, "entry_type", "")) or "")
        for line in content.splitlines():
            stripped = line.strip()
            if len(stripped) < PREMISE_GUARD_MIN_ANCHOR_CHARS:
                continue
            if _FILLER_RE.match(stripped):
                continue
            if not _ANCHOR_RE.search(line):
                continue
            anchors.append({"text": stripped, "role": role, "fingerprint": _fingerprint(stripped)})
            if len(anchors) >= PREMISE_GUARD_MAX_ANCHORS:
                return anchors
    return anchors


def check_summary(anchors: list[dict], summary: str, limit: int = PREMISE_GUARD_REMINDER_LIMIT) -> list[dict]:
    """Report anchors missing from the folded summary.

    Args:
        anchors: anchors collected before the fold.
        summary: the post-fold summary text.
        limit: max missing anchors reported.

    Returns:
        list of {"text", "role"} for missing anchors (empty when the guard
        is disabled or everything survived).
    """
    with _lock:
        enabled = bool(_state["enabled"])
    if not enabled or not anchors or not summary:
        return []
    missing: list[dict] = []
    seen: set[str] = set()
    for a in anchors:
        text = str(a.get("text", ""))
        fp = a.get("fingerprint") or _fingerprint(text)
        if fp in seen:
            continue
        seen.add(fp)
        if text not in summary:
            missing.append({"text": text[:LOG_TRUNC_120], "role": a.get("role", "")})
            if len(missing) >= limit:
                break
    return missing


def guard_reminder(missing: list[dict]) -> str:
    """Render the one-shot reminder injected into the folded context.

    Returns:
        an empty string when nothing is missing, else a short reminder
        block naming the missing anchors.
    """
    if not missing:
        return ""
    lines = ["[premise-guard] The following earlier premises are not in this summary:"]
    for m in missing[:PREMISE_GUARD_REMINDER_LIMIT]:
        role = f" ({m.get('role', '')})" if m.get("role") else ""
        lines.append(f"- {m.get('text', '')[:LOG_TRUNC_120]}{role}")
    lines.append("Re-check the R4 snapshot for full context if needed.")
    return "\n".join(lines)
