"""run_code tool — execute a model-written program that composes tool calls.

The ``run_code`` tool is the Code Mode / PTC transport: under the ``code``
presentation mode the registry exposes only this reserved tool plus a
generated SDK, so the model writes a program in the configured language
backend (Python today; TypeScript / Rust slots per the multi-language
roadmap) that composes multi-step tool calls in one sandboxed execution
instead of one tool-call per step. Only the program's printed output and
return value re-enter the model context; every tool call the program makes
is still recorded on the tool audit chain by the pipeline.

The framework is LANGUAGE-AGNOSTIC: the language backend owns the file
suffix and the execution command (``backend.execute``), and a language is
rejected only when no backend is registered for it — never by name.

The program is written into the caller's per-Cell program cache area
(``tool_presentation.cell_program_dir``) and executed with a hard timeout,
mirroring the terminal tool's execution posture.
"""

from __future__ import annotations

import logging
import os
import subprocess

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.tool import (
    CODE_RUN_DEFAULT_LANGUAGE,
    CODE_RUN_MAX_CHARS,
    CODE_RUN_MAX_RESULT_CHARS,
    CODE_RUN_TIMEOUT,
)

logger = logging.getLogger(__name__)


def _snip(text: str, limit: int) -> str:
    """Truncate text to a char budget with an ellipsis marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def _make_binding(agent_id: str):
    """Build the ``_praxis_call`` binding injected into run_code programs.

    The binding executes the named tool through the real pipeline so every
    call lands on the audit chain, linked to the run_code call as parent
    (the pipeline wraps this handler in ``trace_scope(call_id)``, so the
    current trace id IS the run_code call id).
    """
    from l3.error_bus.core import get_trace_id
    from l3.tool_system.tool_pipeline import get_pipeline

    def _praxis_call(tool_name: str, **kwargs) -> dict:
        return get_pipeline().execute(
            tool_name,
            agent_id,
            args=kwargs or {},
            _parent_call_id=get_trace_id() or "",
        )

    return _praxis_call


def _exec_program_inline(program: str, agent_id: str, timeout: float) -> dict:
    """Execute a Python program in-process with injected tool bindings.

    The program runs in a worker thread under a hard timeout (threading, not
    SIGALRM — ``signal.signal`` only works in the main thread, while the
    pipeline may execute tools on a ThreadPoolExecutor). Its stdout is
    captured and only the captured output re-enters the model context.
    Every SDK binding call (``_praxis_call``) executes the real tool through
    the pipeline and is recorded on the audit chain.
    """
    import io
    import threading
    from contextlib import redirect_stdout

    namespace: dict = {"_praxis_call": _make_binding(agent_id), "__name__": "__main__"}
    buf = io.StringIO()
    outcome: dict = {}

    def _run() -> None:
        try:
            with redirect_stdout(buf):
                exec(compile(program, "<run_code>", "exec"), namespace)  # noqa: S102 - DANGER-3 tool
            outcome["success"] = True
            outcome["stdout"] = buf.getvalue()
        except Exception as e:  # program error — report, do not crash the pipeline
            outcome["success"] = False
            outcome["error"] = f"program error: {e}"
            outcome["stdout"] = buf.getvalue()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return {"success": False, "error": f"run_code program timed out after {timeout}s"}
    return {
        "success": outcome.get("success", False),
        "error": outcome.get("error", ""),
        "stdout": outcome.get("stdout", ""),
    }


def _exec_backend(backend, program_path, program: str, agent_id: str, timeout: float, cache_dir) -> dict:
    """Execute a program via the language backend.

    Python programs run in-process with injected tool bindings so every SDK
    binding call executes the real tool through the pipeline (audit chain,
    run_code call as parent). Other languages fall back to ``backend.execute``
    (subprocess).
    """
    if backend.language == "python":
        res = _exec_program_inline(program, agent_id, timeout)
        success = res.get("success", False)
        return {
            "success": success,
            "result": _snip(res.get("stdout", ""), CODE_RUN_MAX_RESULT_CHARS),
            "error": res.get("error", ""),  # surfaced alongside logs for parity
            "logs": _snip(res.get("error", ""), CODE_RUN_MAX_RESULT_CHARS // 4),
            "exit_code": 0 if success else 1,
            "cache_dir": str(cache_dir),
            "bindings_wired": True,
        }
    try:
        proc = backend.execute(program_path, timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "result": _snip(proc.stdout or "", CODE_RUN_MAX_RESULT_CHARS),
            "logs": _snip(proc.stderr or "", CODE_RUN_MAX_RESULT_CHARS // 4),
            "exit_code": proc.returncode,
            "cache_dir": str(cache_dir),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"program timed out after {timeout}s", "cache_dir": str(cache_dir)}
    except Exception as e:  # pragma: no cover - defensive at the boundary
        return {"success": False, "error": str(e), "cache_dir": str(cache_dir)}


def run_code(args: dict, agent_id: str) -> dict:
    """Execute a model-written program that composes tool calls.

    Args:
        args: dict with ``program`` (required), ``language`` (optional,
            defaults to the configured language backend), and ``cell_id``
            (optional, for the per-Cell program cache area).
        agent_id: calling agent id (audit attribution).

    Returns:
        dict with success flag, program stdout, and the per-Cell cache path.
    """
    program = str(args.get("program", "") or "")
    language = str(args.get("language", "") or CODE_RUN_DEFAULT_LANGUAGE).lower()
    cell_id = str(args.get("cell_id", "") or "")

    from l3.tool_system.tool_presentation import (
        cell_program_dir,
        get_language_backend,
        presentation_status,
    )

    backend = get_language_backend(language)
    error = ""
    if not program.strip():
        error = "program is required"
    elif len(program) > CODE_RUN_MAX_CHARS:
        error = f"program exceeds {CODE_RUN_MAX_CHARS} chars"
    elif backend is None:
        available = ", ".join(presentation_status()["languages"]) or "none"
        error = f"no language backend for '{language}' (available: {available})"
    if error:
        return {"success": False, "error": error}

    from l3.tool_system.run_code_cache import get_run_code_cache

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
    program_path = cache_dir / f"run_{agent_id.replace(os.sep, '_')}{backend.file_suffix}"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        program_path.write_text(program, encoding="utf-8")
    except OSError as e:
        return {"success": False, "error": f"cannot prepare program: {e}"}

    timeout = float(get_tool_config("code_run_timeout", CODE_RUN_TIMEOUT))
    result = _exec_backend(backend, program_path, program, agent_id, timeout, cache_dir)
    # Phase 1.5 write-back: cache successful programs + results so a later
    # approximate hit reuses them (input/output savings). Failures are not
    # cached. Degrades to a no-op on cache errors (bypass-free side channel).
    if result.get("success"):
        try:
            cache.store(
                cell_id,
                program,
                {"result": result.get("result", ""), "language": language},
            )
            result["cached_writeback"] = True
        except Exception:
            logger.debug("run_code: cache write-back skipped", exc_info=True)
    return result
