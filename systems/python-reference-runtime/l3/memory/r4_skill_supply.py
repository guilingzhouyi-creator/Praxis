"""Session-JSON supply pipeline for skill/memory generalization (P0-①).

Feeds the R4Agent generalization engine from the 3.3 session-management
JSON records — the decision-layer JSON trio (conversation / thought chain
/ tool failures) becomes a structured input source for skill evolution
and memory generalization, closing the memory→skill pipeline gap.

  - ``load_tool_failure_cases`` — aggregate ``*_tools.json`` failure
    records into distill-ready cases ({tool, prompt, knowledge:{error}}).
  - ``load_thought_lessons``   — aggregate ``*_thoughts.json`` reasoning
    chains into lesson candidates (memory→skill distillation input).

Performance: the scan is CACHED on the session-dir mtime — the JSON files
are re-scanned only when the directory changes (new/updated session
records), so the per-tick generalization loop never re-reads the whole
session corpus.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from l1.kernel.params.agent import SRC_SUPPLY_MTIME_TTL
from l1.kernel.params.system import LOG_TRUNC_200

logger = logging.getLogger(__name__)

_lock = threading.RLock()
# session-dir mtime -> cached aggregate (avoids re-scan on every tick).
_cache: dict[str, tuple[float, list[dict]]] = {}
# (mtime_value, cached_at) — throttled probe result (P0-①): after the
# first stat sweep the result is reused for SRC_SUPPLY_MTIME_TTL seconds,
# so a cache-hit path costs zero syscalls.
_mtime_cache: tuple[float, float] = (0.0, 0.0)

_TOOLS_GLOB = "*_tools.json"
_THOUGHTS_GLOB = "*_thoughts.json"


def _session_dir() -> Path:
    try:
        from l1.kernel.paths import get_paths as _gp

        return Path(_gp().data_dir) / "l3a" / "sessions"
    except Exception:
        return Path(".praxis") / "l3a" / "sessions"


def _dir_mtime() -> float:
    """Newest mtime across the session JSON files (TTL-throttled).

    P0-①: after the first glob+stat sweep the result is reused for
    ``SRC_SUPPLY_MTIME_TTL`` seconds — the per-tick probe costs zero
    syscalls on a cache hit, and only re-scans when the TTL expires.
    """
    global _mtime_cache
    now = time.time()
    with _lock:
        if now - _mtime_cache[1] < SRC_SUPPLY_MTIME_TTL:
            return _mtime_cache[0]
    d = _session_dir()
    try:
        if not d.exists():
            mtime = 0.0
        else:
            # Newest mtime across matching files (cheap stat, not content read).
            mtime = max(
                (f.stat().st_mtime for f in d.glob("*_*.json") if f.is_file()),
                default=0.0,
            )
    except OSError:
        mtime = 0.0
    with _lock:
        _mtime_cache = (mtime, time.time())
    return mtime


def _cached(glob: str) -> list[dict]:
    """Return cached aggregate for a JSON glob (re-scan on dir change)."""
    mtime = _dir_mtime()
    with _lock:
        hit = _cache.get(glob)
        if hit and hit[0] == mtime:
            return hit[1]
    d = _session_dir()
    items: list[dict] = []
    try:
        # P2-⑤: file I/O goes through the storage port (TS-friendly —
        # the interface maps onto async I/O in a rewrite without caller
        # changes).
        from l1.kernel.ports.storage import get_storage

        store = get_storage()
        for f in sorted(d.glob(glob)):
            try:
                data = json.loads(store.read_text(str(f)))
                items.append(data)
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    with _lock:
        _cache[glob] = (mtime, items)
    return items


def reset_supply_cache() -> None:
    """Drop the cached aggregates + mtime probe (tests / lifecycle)."""
    global _mtime_cache
    with _lock:
        _cache.clear()
        _mtime_cache = (0.0, 0.0)


def load_tool_failure_cases(limit: int = 200) -> list[dict]:
    """Aggregate session tool-failure JSON records into distill-ready cases.

    Each ``*_tools.json`` failure entry ({turn, tool, error}) becomes a
    case in the format consumed by the distill pipeline
    ({tool, prompt, knowledge:{error}}).

    Args:
        limit: max cases to return (oldest-first, capped).

    Returns:
        List of case dicts (empty when no failure records exist).
    """
    cases: list[dict] = []
    for data in _cached(_TOOLS_GLOB):
        sid = data.get("session_id", "")
        for f in data.get("failures", []) or []:
            tool = f.get("tool", "?")
            err = f.get("error", "") or ""
            cases.append(
                {
                    "tool": tool,
                    "prompt": f"[session:{sid}] {tool}: {err[:LOG_TRUNC_200]}",
                    "knowledge": {"error": err[:LOG_TRUNC_200], "tool": tool, "source": "session_tool_failures"},
                    "layer": "exec",
                }
            )
    return cases[:limit]


def load_thought_lessons(limit: int = 200) -> list[dict]:
    """Aggregate session thought-chain JSON records into lesson candidates.

    The chain-of-thought (``*_thoughts.json``) carries reasoning patterns
    worth distilling into decision-layer skills — the memory→skill
    pipeline input (R3 reasoning trails persisted as JSON).

    Args:
        limit: max lessons to return.

    Returns:
        List of lesson dicts ({tool: "thought", prompt, knowledge}).
    """
    lessons: list[dict] = []
    for data in _cached(_THOUGHTS_GLOB):
        sid = data.get("session_id", "")
        for t in data.get("thoughts", []) or []:
            text = t.get("content", "") or ""
            lessons.append(
                {
                    "tool": "thought",
                    "prompt": f"[session:{sid}] turn:{t.get('turn', 0)} seq:{t.get('seq', 0)} {text[:LOG_TRUNC_200]}",
                    "knowledge": {"lesson": text[:LOG_TRUNC_200], "tool": "thought", "source": "session_thoughts"},
                    "layer": "decision",
                }
            )
    return lessons[:limit]
