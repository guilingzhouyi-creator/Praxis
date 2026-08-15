"""Tests for ApprovalGate — request lifecycle, timeout, persist."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import l3.card.approval_gate as approval_gate
from l3.card.approval_gate import ApprovalGate, reset_gate


def setup_method():
    reset_gate()


def teardown_method():
    reset_gate()


@pytest.fixture
def gate(tmp_path):
    current = ApprovalGate(persist_path=str(tmp_path / "approval_gate.json"))
    yield current
    current._stop_auto_save()


def test_request_and_approve(gate):
    req = gate.request("write_file", "agent-a", {"path": "/tmp/test.py"}, "test write")
    req_id = req.id

    r = gate.respond(req_id, True, "approved by test")
    assert r.get("success"), f"approve failed: {r}"


def test_request_and_reject(gate):
    req = gate.request("delete", "agent-b", {"path": "/tmp/secret"}, "reject test")
    req_id = req.id

    r = gate.respond(req_id, False, "not allowed")
    assert r.get("success"), f"reject failed: {r}"


def test_list_pending(gate):
    gate.request("edit", "agent-c", {"path": "/tmp/a.py"}, "pending a")
    gate.request("edit", "agent-d", {"path": "/tmp/b.py"}, "pending b")
    pending = gate.list_pending()
    assert len(pending) == 2


def test_timeout_reject(gate):
    req = gate.request("deploy", "agent-e", {"target": "production"}, "timeout test")
    req_id = req.id

    r = gate.respond(req_id, False, "timeout")
    assert r.get("success"), f"timeout reject failed: {r}"


def test_reset_gate_stops_auto_save(tmp_path, monkeypatch):
    persist_path = str(tmp_path / "shared_approval_gate.json")
    monkeypatch.setattr(approval_gate, "_gp", lambda: SimpleNamespace(approval_gate=persist_path))

    current = approval_gate.get_gate()
    stop = current._auto_save_stop
    assert stop is not None

    approval_gate.reset_gate()

    assert stop.is_set()
