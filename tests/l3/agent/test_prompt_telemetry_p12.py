"""P1.2 slice tests — versioned durable prompt telemetry + RC-period report."""

from __future__ import annotations

import json

import pytest

from l3.agent import prompt_monitor as pm
from l3.durable_store import DurableJsonStore


@pytest.fixture()
def mon(monkeypatch, tmp_path):
    """Isolated monitor: enabled, ledger in tmp, clean live metrics."""
    store = DurableJsonStore(tmp_path / "prompts" / "usage.json", kind="l3a_prompt_usage")
    monkeypatch.setattr(pm, "_ledger", lambda: store)
    monkeypatch.setattr(pm, "_current_version", lambda key: 3)
    pm.set_prompt_monitor(enabled=True, internal=True)
    pm._metrics.clear()
    store.reset()
    yield pm, store
    pm.reset_prompt_monitor()
    store.reset()


def test_usage_and_outcome_landed_by_version(mon):
    pm, store = mon
    pm.record_prompt_usage("agent_terminal.direct")
    pm.record_prompt_outcome("agent_terminal.direct", success=True)
    data = store.read()
    e = data["entries"]["agent_terminal.direct@v3"]
    assert e["used"] == 1
    assert e["ok"] == 1
    assert e["fail"] == 0
    assert e["version"] == 3


def test_report_aggregates_versions_without_text(mon):
    pm, _ = mon
    pm.record_prompt_usage("k1")
    pm.record_prompt_outcome("k1", success=True)
    rep = pm.prompt_usage_report()
    assert rep["success"] is True
    entry = rep["per_key_version"]["k1@v3"]
    assert entry["used"] == 1 and entry["ok"] == 1
    assert "success_rate" in entry
    # privacy contract: no text payloads anywhere in the report
    assert all(k not in json.dumps(rep) for k in ("content", "prompt_text", "reasoning"))


def test_ledger_survives_monitor_reset(mon):
    """P1.2 core: telemetry is cross-restart durable."""
    pm, store = mon
    pm.record_prompt_usage("durable-key")
    pm.reset_prompt_monitor()  # wipes switch+live only
    data = store.read()
    assert "durable-key@v3" in data["entries"]


def test_disabled_monitor_records_nothing(mon):
    pm, store = mon
    pm.set_prompt_monitor(enabled=False, internal=True)
    pm.record_prompt_usage("quiet")
    pm.record_prompt_outcome("quiet", success=False)
    assert store.read().get("entries", {}) == {}
