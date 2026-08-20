"""Protocol v1 event projection — one session state, per-frontend shapes.

Pure functions: a projection consumes the protocol-shaped session-state
snapshot (identity + unacked events) and returns a frontend-ready shape.
No side effects and no imports from L3/L4, so the TS mirror can port the
exact same contract.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Projection = Callable[[dict[str, Any]], dict[str, Any]]

_REGISTRY: dict[str, Projection] = {}


def register_projection(frontend: str, fn: Projection) -> None:
    """Register a projection function for one frontend shape."""
    _REGISTRY[frontend] = fn


def available_frontends() -> list[str]:
    """Return the registered frontend names in stable order."""
    return sorted(_REGISTRY)


def project(frontend: str, state: dict[str, Any]) -> dict[str, Any]:
    """Project one session-state snapshot into a frontend shape.

    An unknown frontend falls back to the web shape so a new adapter can
    adopt the protocol before its projection ships.
    """
    fn = _REGISTRY.get(frontend) or _REGISTRY.get("web")
    return fn(state)


def _summarize(event: dict[str, Any]) -> str:
    """Derive a one-line summary from a protocol event."""
    payload = event.get("payload", {})
    if isinstance(payload, dict):
        if "name" in payload:
            return str(payload["name"])
        if "error" in payload:
            return str(payload["error"])
    return str(event.get("kind", ""))


def _web(state: dict[str, Any]) -> dict[str, Any]:
    """Web shape: protocol pass-through with session metadata."""
    return {"frontend": "web", "session": state.get("identity", {}), "events": state.get("events", [])}


def _tui(state: dict[str, Any]) -> dict[str, Any]:
    """TUI shape: table-ready rows over the event stream."""
    identity = state.get("identity", {})
    rows = [
        {"seq": event.get("seq", 0), "kind": event.get("kind", ""), "summary": _summarize(event)}
        for event in state.get("events", [])
    ]
    return {
        "frontend": "tui",
        "headers": ["seq", "kind", "summary"],
        "rows": rows,
        "session_id": identity.get("session_id", ""),
    }


def _desktop(state: dict[str, Any]) -> dict[str, Any]:
    """Desktop shape: rich-text blocks over the session and events."""
    identity = state.get("identity", {})
    blocks = [
        {"type": "heading", "text": f"Session {identity.get('session_id', '')}"},
        {"type": "text", "text": f"role={identity.get('role', '')} cell={identity.get('cell_id', '')}"},
    ]
    for event in state.get("events", []):
        blocks.append({"type": "event", "seq": event.get("seq", 0), "kind": event.get("kind", "")})
    return {"frontend": "desktop", "blocks": blocks}


register_projection("web", _web)
register_projection("tui", _tui)
register_projection("desktop", _desktop)
