"""Guard the single execution gate (W1.2/W1.4).

The registry-level executor (``tool_spec._execute_tool_spec``) may only be
called from the tool pipeline itself. Every other caller — L2 shell, MCP,
API handlers, LLM engines — must enter through ``invoke_gated`` so the full
gate chain always applies. This mirrors test_process_port_usage.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIRS = (ROOT / "src" / "l2", ROOT / "src" / "l3", ROOT / "src" / "l4")

# Modules allowed to call the registry-level executor directly.
EXECUTOR_ALLOWLIST = frozenset({
    "tool_pipeline_steps.py",  # the pipeline's own execute step
    "tool_spec.py",  # the executor definition itself
})


def _runtime_modules() -> list[Path]:
    """Return production Python modules covered by the single-gate rule."""
    return [path for directory in RUNTIME_DIRS for path in directory.rglob("*.py")]


def _direct_executor_calls() -> list[str]:
    """Return (path:line) entries calling the executor outside the allowlist."""
    offenders: list[str] = []
    for path in _runtime_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if name in ("execute_tool_spec", "_execute_tool_spec"):
                if path.name in EXECUTOR_ALLOWLIST:
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} calls {name}")
    return offenders


def test_no_direct_executor_calls_outside_pipeline() -> None:
    """No production caller may bypass the pipeline to reach a tool handler."""
    bad = _direct_executor_calls()
    assert not bad, "direct executor calls outside the tool pipeline:\n" + "\n".join(bad)
