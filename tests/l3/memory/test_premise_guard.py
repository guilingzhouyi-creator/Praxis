"""Tests for the premise guard (premise-guard)."""

from __future__ import annotations

from l3.memory.premise_guard import (
    check_summary,
    extract_anchors,
    guard_reminder,
    premise_guard_status,
    reset_premise_guard,
    set_premise_guard,
)


def _reset():
    reset_premise_guard()


def test_default_enabled():
    _reset()
    try:
        assert premise_guard_status()["enabled"] is True
    finally:
        _reset()


def test_extract_anchors_finds_constraints():
    _reset()
    try:
        msgs = [
            {"role": "user", "content": "Constraint: never write outside the workspace"},
            {"role": "user", "content": "ok sounds good"},
            {"role": "user", "content": "Requirement: the reader agent stays on ring 1"},
        ]
        anchors = extract_anchors(msgs)
        texts = [a["text"] for a in anchors]
        assert any("never write outside" in t for t in texts)
        assert any("reader agent stays on ring 1" in t for t in texts)
        assert not any("ok sounds good" in t for t in texts), "filler must not anchor"
    finally:
        _reset()


def test_check_summary_reports_missing():
    _reset()
    try:
        anchors = [
            {"text": "Constraint: never write outside the workspace", "role": "user", "fingerprint": "a"},
            {"text": "Decision: keep reader on ring 1", "role": "user", "fingerprint": "b"},
        ]
        summary = "HEADLINE: user intent\nCARD: built the module"
        missing = check_summary(anchors, summary)
        assert len(missing) == 2, "both anchors must be reported missing"
    finally:
        _reset()


def test_check_summary_keeps_present_anchors():
    _reset()
    try:
        anchors = [{"text": "Constraint: never write outside the workspace", "role": "user", "fingerprint": "a"}]
        summary = "HEADLINE: ok\nConstraint: never write outside the workspace"
        assert check_summary(anchors, summary) == []
    finally:
        _reset()


def test_guard_reminder_renders():
    _reset()
    try:
        missing = [{"text": "Constraint: never write outside the workspace", "role": "user"}]
        reminder = guard_reminder(missing)
        assert "[premise-guard]" in reminder
        assert "never write outside" in reminder
        assert guard_reminder([]) == ""
    finally:
        _reset()


def test_guard_disabled_returns_empty():
    _reset()
    try:
        set_premise_guard(False)
        anchors = [{"text": "Constraint: never write outside the workspace", "role": "user", "fingerprint": "a"}]
        assert check_summary(anchors, "summary without it") == []
    finally:
        _reset()
