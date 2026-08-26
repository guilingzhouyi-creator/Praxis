"""Tests for the system-prompt bypass monitor (3.2, P1-⑥)."""

from __future__ import annotations

from l3.agent.prompt_monitor import (
    emit_prompt_metrics,
    prompt_monitor_stats,
    prompt_monitor_status,
    record_prompt_outcome,
    record_prompt_usage,
    reset_prompt_monitor,
    set_prompt_monitor,
)


def test_disabled_by_default_production_mode():
    reset_prompt_monitor()
    try:
        assert prompt_monitor_status()["enabled"] is False  # production
    finally:
        reset_prompt_monitor()


def test_usage_and_outcome_records_when_enabled():
    reset_prompt_monitor()
    try:
        set_prompt_monitor(enabled=True)
        record_prompt_usage("agent_loop.system")
        record_prompt_usage("agent_loop.system")
        record_prompt_outcome("agent_loop.system", success=True)
        record_prompt_outcome("agent_loop.system", success=False)
        stats = prompt_monitor_stats()
        entry = stats["per_prompt"]["agent_loop.system"]
        assert entry["used"] == 2
        assert entry["ok"] == 1
        assert entry["fail"] == 1
        assert entry["success_rate"] == 0.5
    finally:
        reset_prompt_monitor()


def test_disabled_records_nothing():
    reset_prompt_monitor()
    try:
        record_prompt_usage("agent_loop.system")
        assert prompt_monitor_stats()["total_usage"] == 0
    finally:
        reset_prompt_monitor()


def test_emit_prompt_metrics_to_rc(tmp_path, monkeypatch):
    monkeypatch.setenv("PRAXIS_RC_PATH", str(tmp_path / "rc.jsonl"))
    from l3.bus.reference_channel import get_rc, reset_rc

    reset_rc()
    reset_prompt_monitor()
    try:
        set_prompt_monitor(enabled=True)
        record_prompt_usage("agent_loop.system")
        r = emit_prompt_metrics()
        assert r["success"] is True
        assert r["emitted"] == 1
        rc = get_rc()
        rc.flush()
        assert rc.count("prompt_metrics") == 1
    finally:
        reset_prompt_monitor()
        reset_rc()


def test_monitored_get_prompt_counts_usage():
    reset_prompt_monitor()
    try:
        set_prompt_monitor(enabled=True)
        from l3.agent.prompt_monitor import install_prompt_hook

        assert install_prompt_hook() is True
        from l3.agent.prompts import get_prompt_monitored

        get_prompt_monitored("agent_loop.system.default", "fallback")
        assert prompt_monitor_stats()["per_prompt"]["agent_loop.system.default"]["used"] == 1
    finally:
        reset_prompt_monitor()


def test_register_prompt_source_covers_record_center():
    """P2-3: the prompt record source folds into RecordCenter stats/export."""
    from l3.agent import prompt_monitor
    from l3.services.record_center import get_record_center, reset_record_center

    reset_record_center()
    reset_prompt_monitor()
    try:
        set_prompt_monitor(enabled=True)
        prompt_monitor.record_prompt_usage("agent_loop.system")
        r = prompt_monitor.register_prompt_source()
        assert r["success"] is True

        rc = get_record_center()
        stats = rc.stats()
        assert "prompt" in stats
        assert stats["prompt"]["tracked_keys"] == 1

        export = rc.export(sources=["prompt"])
        assert export["success"] is True
        assert export["total"] >= 0
    finally:
        reset_prompt_monitor()
        reset_record_center()
