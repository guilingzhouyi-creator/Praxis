"""run_code tool — execute a model-written program that composes tool calls.

The ``run_code`` tool is the Code Mode / PTC transport: under the ``code``
presentation mode the registry exposes only this reserved tool plus a
generated SDK, so the model writes a program (Python today; TypeScript /
Rust slots are open on the multi-language roadmap) that composes multi-step
tool calls in one sandboxed execution instead of one tool-call per step.
Only the program's printed output and return value re-enter the model
context; every tool call the program makes is still recorded on the tool
audit chain by the pipeline.

The program is written into the caller's per-Cell program cache area
(``tool_presentation.cell_program_dir``) and executed as a subprocess with
a hard timeout, mirroring the terminal tool's execution posture.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.tool import (
    CODE_RUN_DEFAULT_LANGUAGE,
    CODE_RUN_MAX_CHARS,
    CODE_RUN_MAX_RESULT_CHARS,
    CODE_RUN_TIMEOUT,
)
from l1.kernel.platform import run_shell

logger = logging.getLogger(__name__)


def _snip(text: str, limit: int) -> str:
    """Truncate text to a char budget with an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def run_code(args: dict, agent_id: str) -> dict:
    """Execute a model-written program that composes tool calls.

    Args:
        args: dict with ``program`` (required), ``language`` (optional,
            default "python"), and ``cell_id`` (optional, for the per-Cell
            program cache area).
        agent_id: calling agent id (audit attribution).

    Returns:
        dict with success flag, program stdout, and the per-Cell cache path.
    """
    program = str(args.get("program", "") or "")
    language = str(args.get("language", "") or CODE_RUN_DEFAULT_LANGUAGE).lower()
    cell_id = str(args.get("cell_id", "") or "")
    error = ""
    if not program.strip():
        error = "program is required"
    elif len(program) > CODE_RUN_MAX_CHARS:
        error = f"program exceeds {CODE_RUN_MAX_CHARS} chars"
    elif language != "python":
        error = f"unsupported language: {language} (python is the shipped renderer)"
    if error:
        return {"success": False, "error": error}

    from l3.tool_system.run_code_cache import get_run_code_cache
    from l3.tool_system.tool_presentation import cell_program_dir

    # Phase 1.5: reuse a cached program when an approximate hit exists — the
    # caller then supplies only an incremental patch instead of the full
    # program (input savings), and the matched entry's TTL is renewed.
    cache = get_run_code_cache()
    hit = cache.similar(cell_id, program)
    if hit and hit.get("program"):
        cache.renew(cell_id, str(hit.get("program", "")))
        cache.record_patch(cell_id, program, str(hit.get("program", "")))
        return {
            "success": True,
            "cached": True,
            "result": str(hit.get("result", "") or ""),
            "cached_program": str(hit.get("program", ""))[:CODE_RUN_MAX_RESULT_CHARS],
            "cache_dir": str(cell_program_dir(cell_id)),
            "note": "approximate program-cache hit — submit only the incremental patch",
        }

    cache_dir = cell_program_dir(cell_id)
    program_path = cache_dir / f"run_{agent_id.replace(os.sep, '_')}.py"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        program_path.write_text(program, encoding="utf-8")
    except OSError as e:
        return {"success": False, "error": f"cannot prepare program: {e}"}

    timeout = float(get_tool_config("code_run_timeout", CODE_RUN_TIMEOUT))
    cmd = f"{sys.executable} {program_path}"
    try:
        proc = run_shell(cmd, timeout=timeout)
        stdout = _snip(proc.stdout or "", CODE_RUN_MAX_RESULT_CHARS)
        stderr = _snip(proc.stderr or "", CODE_RUN_MAX_RESULT_CHARS // 4)
        return {
            "success": proc.returncode == 0,
            "result": stdout,
            "logs": stderr,
            "exit_code": proc.returncode,
            "cache_dir": str(cache_dir),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"program timed out after {timeout}s",
            "cache_dir": str(cache_dir),
        }
    except Exception as e:  # pragma: no cover - defensive at the boundary
        return {"success": False, "error": str(e), "cache_dir": str(cache_dir)}
