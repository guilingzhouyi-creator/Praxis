"""Guard the single execution gate (W1.2/W1.4).

The registry-level executor (``tool_spec._execute_tool_spec``) may only be
called from the tool pipeline itself. Every other caller — L2 shell, MCP,
API handlers, LLM engines — must enter through ``invoke_gated`` so the full
gate chain always applies.

Parameterized from ``config/quality/single-execution-gate.json`` (pre-computed
scan results). The gate test compares against the snapshot instead of
re-scanning the entire codebase.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = ROOT / "config" / "quality" / "single-execution-gate.json"

_SNAPSHOT: dict | None = None


def _snapshot() -> dict:
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return _SNAPSHOT


def test_no_direct_executor_calls_outside_pipeline() -> None:
    """No production caller may bypass the pipeline to reach a tool handler."""
    bad = _snapshot().get("offenders", [])
    assert not bad, "direct executor calls outside the tool pipeline:\n" + "\n".join(bad)
