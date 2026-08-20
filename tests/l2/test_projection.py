"""Event projection tests — one session state, per-frontend shapes.

Pins the pure projection contract so the TS mirror can port identical
expectations: web pass-through, TUI table rows, desktop rich-text blocks,
and the unknown-frontend fallback.
"""

from __future__ import annotations

from l2.protocol.projection import available_frontends, project

IDENTITY = {
    "session_id": "s-1",
    "terminal_id": "",
    "process_id": "",
    "user_id": "",
    "role": "operator",
    "cell_id": "cell-a",
    "memory_scope": "",
}

STATE = {
    "identity": IDENTITY,
    "events": [
        {"seq": 1, "kind": "event", "payload": {"name": "session.attached"}},
        {"seq": 2, "kind": "result", "payload": {"success": True, "error": ""}},
    ],
}


def test_web_shape_passes_through() -> None:
    """Web projection keeps the protocol shape with session metadata."""
    out = project("web", STATE)
    assert out["frontend"] == "web"
    assert out["session"]["session_id"] == "s-1"
    assert len(out["events"]) == 2


def test_tui_shape_renders_table_rows() -> None:
    """TUI projection emits table-ready rows with stable headers."""
    out = project("tui", STATE)
    assert out["frontend"] == "tui"
    assert out["headers"] == ["seq", "kind", "summary"]
    assert out["rows"][0] == {"seq": 1, "kind": "event", "summary": "session.attached"}
    assert out["session_id"] == "s-1"


def test_desktop_shape_renders_blocks() -> None:
    """Desktop projection emits rich-text blocks."""
    out = project("desktop", STATE)
    assert out["frontend"] == "desktop"
    assert out["blocks"][0]["type"] == "heading"
    assert out["blocks"][1]["type"] == "text"
    assert out["blocks"][2]["type"] == "event"


def test_unknown_frontend_falls_back_to_web() -> None:
    """A new frontend adopts the protocol before its projection ships."""
    out = project("ide-lsp", STATE)
    assert out["frontend"] == "web"


def test_registered_frontends_are_stable() -> None:
    """The registry is a stable, sorted set."""
    assert available_frontends() == ["desktop", "tui", "web"]
