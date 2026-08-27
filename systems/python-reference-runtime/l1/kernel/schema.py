"""Kernel string-event schema registry (W4.3).

SignalType (event.py) is the typed kernel bus surface; this module is the
catalog for STRING events emitted across L3 buses. Every event name must be
registered here with its owner before production use — a test enforces the
catalog is populated at boot. Ordering contract: FIFO within one channel,
no ordering guarantees across channels.
"""

from __future__ import annotations

import threading

_EVENTS: dict[str, dict] = {}
_LOCK = threading.Lock()


def register_event(name: str, owner: str, description: str = "") -> bool:
    """Register a string event name with its owning subsystem.

    Returns False when the name is already registered with a different owner.
    """
    with _LOCK:
        existing = _EVENTS.get(name)
        if existing and existing["owner"] != owner:
            return False
        _EVENTS[name] = {"owner": owner, "description": description}
        return True


def has_event(name: str) -> bool:
    """True when *name* is registered in the schema."""
    return name in _EVENTS


def list_events() -> list[dict]:
    """Registered events as a sorted list of {name, owner, description}."""
    with _LOCK:
        return [{"name": n, **e} for n, e in sorted(_EVENTS.items())]


def reset_event_schema() -> None:
    """Drop all registrations (tests / factory reset)."""
    global _EVENTS
    with _LOCK:
        _EVENTS = {}
