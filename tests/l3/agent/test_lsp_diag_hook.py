"""LSP diagnostics hook + fix-loop test for _process_tool_results.

Covers the AgentLoop error -> line -> fix path added in the line-loc
feature: a failed file tool with LSP diagnostics must trigger exactly one
fix-generation round-trip and one cell L2 cache inject; a result without
diagnostics must trigger zero LLM calls; looped steps must be stopped
before any LLM work happens.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))


class _FakeLoopDetector:
    def check(self, tool_name: str, args: dict, step_result: dict) -> str:
        return ""


class _FakeRepeatDetector:
    def check(self, tool_name: str) -> str:
        return ""


class _FakeCadence:
    def record_edit(self, path: str) -> None:
        pass

    def record_check(self, command: str) -> None:
        pass


class _FakePmu:
    def increment(self, key: str) -> None:
        pass


class _FakeEngine:
    def __init__(self) -> None:
        self.generations = 0

    def generate(self, prompt: str, system: str, user_id: str, **kwargs) -> dict:
        self.generations += 1
        return {"content": "fix: replace old_str with new_str at line 3"}


class _FakeMgr:
    """Fake LspManager: returns a single line-3 error diagnostic."""

    def __init__(self, has_diag: bool = True) -> None:
        self.has_diag = has_diag

    def get_diagnostics(self, file_path: str) -> dict:
        if not self.has_diag:
            return {"success": True, "diagnostics": [], "summary": ""}
        return {
            "success": True,
            "source": "ast",
            "diagnostics": [
                {"file": file_path, "line": 3, "column": 0, "message": "undefined name", "severity": "error"}
            ],
            "summary": "1 error",
        }


class _FakeCell:
    def __init__(self) -> None:
        self.injects: list[dict] = []

    @property
    def cache(self):
        return self

    def inject(self, **kwargs) -> None:
        self.injects.append(kwargs)


class _Host:
    """Minimal host with the attributes _process_tool_results touches."""

    def __init__(self, loop_stop: bool = False, repeat_stop: bool = False) -> None:
        self.agent_id = "test-agent"
        self.task = "fix the test file"
        self._user_id = "test-user"
        self._cell_id = "cell-1"
        self._loop_detector = _FakeLoopDetector()
        self._repeat_detector = _FakeRepeatDetector()
        self._cadence = _FakeCadence()
        self._pmu = _FakePmu()
        self._loop_stop = loop_stop
        self._repeat_stop = repeat_stop
        self._context_trail: list[dict] | None = None

    # _loop_detector.check returns "" normally; loop-stopped returns "stop"
    def _install_loop_stop(self) -> None:
        class _StopDetector:
            def check(self, tool_name: str, args: dict, step_result: dict) -> str:
                return "stop"

        self._loop_detector = _StopDetector()

    def _install_repeat_stop(self) -> None:
        class _StopRepeat:
            def check(self, tool_name: str) -> str:
                return "stop"

        self._repeat_detector = _StopRepeat()


def _call_process(host: _Host, engine: _FakeEngine, tool_results: list, deadline: float) -> dict:
    from l3.agent.agent_loop_guard import AgentLoopGuardMixin

    method = AgentLoopGuardMixin._process_tool_results
    result: dict = {"content": "", "steps": []}
    side_times: dict[str, float] = {}
    processed, all_passed, corrections, verifier_used = method(
        host,
        tool_results=tool_results,
        result=result,
        system="You are a test agent.",
        engine=engine,
        model_kwargs={},
        deadline=deadline,
        verifier=None,
        side_times=side_times,
    )
    return {"processed": processed, "all_passed": all_passed, "result": result}


def test_diag_hook_injects_fix_once(monkeypatch) -> None:
    """Failed file tool + diagnostics → exactly one generate + one cache inject."""
    host = _Host()
    engine = _FakeEngine()
    cell = _FakeCell()
    monkeypatch.setattr("l4.lsp.lsp_manager.get_manager", lambda: _FakeMgr(has_diag=True))
    monkeypatch.setattr("l3.cell.get_cell", lambda cell_id: cell)

    tool_results = [
        {
            "name": "file_edit",
            "args": {"path": "systems/python-reference-runtime/x.py"},
            "result": {"success": False, "error": "old_str not found", "file": "systems/python-reference-runtime/x.py"},
        }
    ]
    out = _call_process(host, engine, tool_results, deadline=10**12)
    step = out["processed"][0]
    assert engine.generations == 1
    assert step.get("_diag"), "line-level diagnostics must be attached"
    assert step["_diag"][0]["line"] == 3
    assert step.get("_diag_fix"), "fix suggestion must be attached"
    assert step["_diag_fix"].startswith("fix:")
    assert len(cell.injects) == 1
    assert cell.injects[0]["key"].startswith("fix:test-agent:file_edit:")


def test_no_diag_no_llm_call(monkeypatch) -> None:
    """No diagnostics → zero LLM round-trips (no cost explosion)."""
    host = _Host()
    engine = _FakeEngine()
    monkeypatch.setattr("l4.lsp.lsp_manager.get_manager", lambda: _FakeMgr(has_diag=False))

    tool_results = [
        {
            "name": "file_edit",
            "args": {"path": "systems/python-reference-runtime/x.py"},
            "result": {"success": False, "error": "old_str not found", "file": "systems/python-reference-runtime/x.py"},
        }
    ]
    out = _call_process(host, engine, tool_results, deadline=10**12)
    assert engine.generations == 0
    step = out["processed"][0]
    assert "_diag" not in step
    assert "_diag_fix" not in step


def test_looped_step_skips_llm(monkeypatch) -> None:
    """Loop-stopped step → hook must not run (no LLM for a step that halts)."""
    host = _Host()
    host._install_loop_stop()
    engine = _FakeEngine()
    monkeypatch.setattr("l4.lsp.lsp_manager.get_manager", lambda: _FakeMgr(has_diag=True))

    tool_results = [
        {
            "name": "file_edit",
            "args": {"path": "systems/python-reference-runtime/x.py"},
            "result": {"success": False, "error": "old_str not found", "file": "systems/python-reference-runtime/x.py"},
        }
    ]
    out = _call_process(host, engine, tool_results, deadline=10**12)
    assert engine.generations == 0
    assert out["processed"][0].get("_loop_stopped") is True


def test_deadline_guard_skips_llm(monkeypatch) -> None:
    """Deadline exceeded → hook must not run (turn overshoot guard)."""
    import time

    host = _Host()
    engine = _FakeEngine()
    monkeypatch.setattr("l4.lsp.lsp_manager.get_manager", lambda: _FakeMgr(has_diag=True))

    tool_results = [
        {
            "name": "file_edit",
            "args": {"path": "systems/python-reference-runtime/x.py"},
            "result": {"success": False, "error": "old_str not found", "file": "systems/python-reference-runtime/x.py"},
        }
    ]
    out = _call_process(host, engine, tool_results, deadline=time.time() - 1)
    assert engine.generations == 0
    assert out["result"].get("finish_reason") == "timeout"
