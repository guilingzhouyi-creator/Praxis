"""Memory compaction extractor — hybrid deterministic/LLM content selection.

The compaction front end for memory and L3A session folding: instead of a
plain string concatenation (or an LLM summary), a deterministic heuristic
extractor keeps high-signal lines — paths, commands, error codes, version
pins, decision anchors — and drops conversational filler, raising the
compression ratio while preserving the facts the agent acts on.

Three operator modes (API + L2 Shell):
  deterministic — heuristic extractor only (default, no LLM)
  llm-assisted  — optional LLM-structured extraction as a bypass enhancer;
                  degrades to deterministic on failure/expiry (never blocks
                  the main flow)
  off           — legacy behavior (concatenate/truncate unchanged)

The extractor is deterministic by construction and never raises: every
failure path falls back to the source text unchanged.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from l1.kernel.params.system import (
    MEMORY_COMPACTION_MAX_LINE_CHARS,
    MEMORY_COMPACTION_MAX_OUTPUT_CHARS,
    MEMORY_COMPACTION_MODE_DEFAULT,
)

logger = logging.getLogger(__name__)

# ── Operator state (switched via API + L2 Shell) ──
_state: dict[str, Any] = {"mode": MEMORY_COMPACTION_MODE_DEFAULT}
_lock = threading.RLock()

# ── Heuristic signals ──
# Lines carrying concrete facts the agent acts on.
_PATH_RE = re.compile(r"(?:[/~][\w.\-/]+){2,}|[\w.\-/]+\.(?:py|ts|js|go|rs|yaml|yml|json|toml|md|sh|cfg|ini)\b")
_COMMAND_RE = re.compile(r"`[^`]{2,}`|\b(?:pip|npm|apt|git|make|cargo|go|python|python3|node|docker|bash)\b[^\n]{0,80}")
_ERROR_RE = re.compile(
    r"\b(?:error|failed|failure|traceback|exception|exit code|timeout|denied|rejected)\b[^\n]{0,100}", re.I
)
_VERSION_RE = re.compile(r"\b(?:v?\d+\.\d+(?:\.\d+)?|version)\b[^\n]{0,60}", re.I)
_DECISION_RE = re.compile(
    r"\b(?:decided|decision|constraint|constraints|requirement|requirements|approved|rejected|blocked|because|note|important|must|never|always)\b[^\n]{0,100}",
    re.I,
)
# Conversational filler: short soft prose lines with no concrete signal.
_FILLER_RE = re.compile(
    r"^(?:ok|okay|yes|no|sure|great|good|thanks|thank you|got it|understood|hmm|i think|probably|maybe)[.!?]?$", re.I
)

# All signal regexes, ordered by specificity (first match wins).
_SIGNALS: tuple[re.Pattern, ...] = (_PATH_RE, _COMMAND_RE, _ERROR_RE, _VERSION_RE, _DECISION_RE)


def compaction_status() -> dict:
    """Return the extractor operator state."""
    with _lock:
        return {"mode": str(_state["mode"])}


def set_compaction_mode(mode: str) -> dict:
    """Set the extractor mode (deterministic | llm-assisted | off).

    Args:
        mode: one of the three supported modes.

    Returns:
        dict with success flag and the effective mode.
    """
    if mode not in ("deterministic", "llm-assisted", "off"):
        return {"success": False, "error": f"unknown compaction mode '{mode}'"}
    with _lock:
        _state["mode"] = mode
    return {"success": True, "mode": mode}


def reset_compaction() -> None:
    """Reset the extractor switch (tests / lifecycle)."""
    with _lock:
        _state["mode"] = MEMORY_COMPACTION_MODE_DEFAULT


def _line_signal(line: str) -> bool:
    """True when a source line carries at least one concrete signal."""
    stripped = line.strip()
    if not stripped:
        return False
    if _FILLER_RE.match(stripped):
        return False
    return any(pat.search(line) for pat in _SIGNALS)


def _fold_long_line(line: str) -> str:
    """Elide a long high-signal line to head+tail."""
    if len(line) <= MEMORY_COMPACTION_MAX_LINE_CHARS:
        return line
    half = MEMORY_COMPACTION_MAX_LINE_CHARS // 2
    return f"{line[:half]} …[{len(line) - MEMORY_COMPACTION_MAX_LINE_CHARS} chars elided]… {line[-half:]}"


def extract_deterministic(text: str, budget: int = MEMORY_COMPACTION_MAX_OUTPUT_CHARS) -> str:
    """Deterministic extraction: keep high-signal lines, drop filler.

    Args:
        text: the source content (entry content or session span).
        budget: max characters the extraction may consume.

    Returns:
        the extracted text (never raises; empty input yields empty output).
    """
    if not text:
        return ""
    kept: list[str] = []
    used = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not _line_signal(line):
            continue
        folded = _fold_long_line(line)
        if used + len(folded) > budget:
            break
        kept.append(folded)
        used += len(folded)
    if not kept:
        return ""
    return "\n".join(kept)


def extract_llm_assisted(text: str, budget: int = MEMORY_COMPACTION_MAX_OUTPUT_CHARS) -> str:
    """LLM-assisted extraction bypass — degrades to deterministic on failure.

    Runs only when the mode is llm-assisted; every failure (no engine,
    expiry, exception) falls back to the deterministic extractor so the
    main flow is never blocked or polluted.
    """
    if not text:
        return ""
    try:
        import l4.llm.llm as _llm_mod

        engine = _llm_mod.get_engine()
        if engine is None:
            return extract_deterministic(text, budget)
        prompt = (
            "Extract the operationally important facts from this text: file paths, commands, "
            "error codes, version pins, decisions and constraints. Return ONLY a compact bullet "
            "list in the original language, at most 8 lines. Drop conversational filler.\n\n"
            f"{text[:4000]}"
        )
        out = engine.generate(prompt, system="You are a lossy-but-precise summarizer.", max_tokens=512)
        content = out.get("content", "") if isinstance(out, dict) else ""
        if content and len(content) <= budget:
            return content
        return extract_deterministic(text, budget)
    except Exception as e:
        logger.debug("compaction: llm-assisted skipped (%s), falling back", e)
        return extract_deterministic(text, budget)


def extract(text: str, budget: int = MEMORY_COMPACTION_MAX_OUTPUT_CHARS) -> str:
    """Extract the high-signal content of a memory entry under the active mode.

    Applies the operator-selected mode; never raises — every path degrades
    to the deterministic extractor or the source text unchanged.
    """
    if not text:
        return ""
    with _lock:
        mode = str(_state["mode"])
    try:
        if mode == "off":
            return text
        if mode == "llm-assisted":
            return extract_llm_assisted(text, budget)
        return extract_deterministic(text, budget)
    except Exception as e:
        logger.debug("compaction: extract degraded (%s)", e)
        return text
