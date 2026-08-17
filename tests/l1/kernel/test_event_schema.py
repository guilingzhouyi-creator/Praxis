"""Event convergence (W4.3) — SignalType freeze + string-event schema."""

from __future__ import annotations

from l1.kernel.event import SignalType

# Frozen built-in surface: adding a member here requires updating this list
# AND registering the event semantics in the schema registry first.
_FROZEN_SIGNAL_TYPES = {
    "TASK_ASSIGN",
    "TASK_CANCEL",
    "REVIEW_RESULT",
    "CONSTITUTION_UPDATE",
    "TASK_DONE",
    "TASK_ACCEPT",
    "TASK_ERROR",
    "DISPUTE_RAISE",
    "AGENT_CRASH",
    "STATE_CHANGE",
    "CROSS_REVIEW_REQ",
    "CROSS_REVIEW_RESP",
    "TERRITORY_QUERY",
    "SCOUT_DONE",
    "REVIEW_REQUESTED",
    "TOKEN_USAGE",
    "FILE_CHANGED",
    "CARD_PENDING",
    "APPROVAL_REQUIRED",
    "APPROVAL_RESPONDED",
}


def test_signal_type_builtin_surface_frozen() -> None:
    """Built-in SignalType members must match the frozen golden set."""
    live = {m.name for m in SignalType}
    assert live == _FROZEN_SIGNAL_TYPES, f"SignalType drift: {live ^ _FROZEN_SIGNAL_TYPES}"


def test_event_schema_registered_with_owners() -> None:
    """Boot must register the L3 string-event catalog with owners."""
    from l1.kernel.schema import list_events, reset_event_schema
    from l3.boot.boot_steps.events import _register_event_schema

    reset_event_schema()
    r = _register_event_schema()
    assert r.get("success") is True, r
    events = list_events()
    assert events, "schema catalog empty"
    assert all(e["owner"] for e in events), "every event needs an owner"
    names = {e["name"] for e in events}
    assert "skill_mutated" in names
    assert "error_log" in names
    assert "security_mode_change" in names
    reset_event_schema()


def test_event_schema_owner_conflict_rejected() -> None:
    """A name claimed by a second owner must be rejected."""
    from l1.kernel.schema import register_event, reset_event_schema

    reset_event_schema()
    assert register_event("dup.event", "owner-a") is True
    assert register_event("dup.event", "owner-b") is False
    assert register_event("dup.event", "owner-a") is True
    reset_event_schema()
