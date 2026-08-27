"""Tests for the deterministic compaction extractor (compaction)."""

from __future__ import annotations

from l3.memory.memory_extract import (
    compaction_status,
    extract,
    extract_deterministic,
    reset_compaction,
    set_compaction_mode,
)

SAMPLE = """ok let me check that
the build failed with exit code 1
Running: pip install requests
Error: ModuleNotFoundError: No module named 'xyz'
source file /home/guiling/dev/praxis/systems/python-reference-runtime/main.py has a syntax error
yes sure
version pin: numpy==1.26.4
decision: keep the reader agent on ring 1
thanks!
Run: pytest tests/l1 -x -q
Constraint: never write outside the workspace
"""


def _reset():
    reset_compaction()


def test_default_mode_deterministic():
    _reset()
    try:
        assert compaction_status()["mode"] == "deterministic"
    finally:
        _reset()


def test_deterministic_keeps_signal_drops_filler():
    _reset()
    try:
        out = extract_deterministic(SAMPLE)
        assert "pip install requests" in out, "command line must be kept"
        assert "exit code 1" in out, "error line must be kept"
        assert "main.py" in out, "path line must be kept"
        assert "numpy==1.26.4" in out, "version pin must be kept"
        assert "reader agent on ring 1" in out, "decision must be kept"
        assert "never write outside" in out, "constraint must be kept"
        assert "ok let me check" not in out, "filler must be dropped"
        assert "yes sure" not in out, "filler must be dropped"
        assert "thanks!" not in out, "filler must be dropped"
    finally:
        _reset()


def test_deterministic_budget_cap():
    _reset()
    try:
        out = extract_deterministic(SAMPLE, budget=60)
        assert len(out) <= 60
    finally:
        _reset()


def test_mode_off_returns_source_unchanged():
    _reset()
    try:
        set_compaction_mode("off")
        assert extract(SAMPLE) == SAMPLE
    finally:
        _reset()


def test_mode_switch_rejects_unknown():
    _reset()
    try:
        r = set_compaction_mode("bogus")
        assert r["success"] is False
    finally:
        _reset()


def test_extract_empty_input():
    _reset()
    try:
        assert extract("") == ""
        assert extract_deterministic("") == ""
    finally:
        _reset()


def test_llm_assisted_falls_back_to_deterministic(monkeypatch):
    """llm-assisted mode degrades to deterministic when the engine fails."""
    _reset()
    try:
        set_compaction_mode("llm-assisted")

        def _boom(*args, **kwargs):
            raise RuntimeError("no engine")

        monkeypatch.setattr("l4.llm.llm.get_engine", _boom)
        out = extract(SAMPLE)
        assert "pip install requests" in out, "deterministic fallback must run"
        assert "ok let me check" not in out
    finally:
        _reset()
