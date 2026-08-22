"""P0.2/P0.3 slice tests — session identity lifecycle and reload reachability.

Covers the agent-os-3x-closure Slice B exit criteria:
  - two concurrent sessions on one terminal stay independently addressable
    (no binding overwrite);
  - identity meta (user_id/role/cell_id/memory_scope) is preserved;
  - detach/close model the lifecycle explicitly and release terminal slots;
  - auto_reload rebuilds workers and fails loudly when restoration is
    incomplete (no fake IDLE).
"""

from __future__ import annotations

import os
import threading

import l3.agent_terminal as at
from l3.agent_terminal import (
    AgentTerminal,
    close_session_binding,
    detach_session,
    get_session,
    list_sessions,
    register_session,
    reset_sessions,
)


def _setup():
    reset_sessions()


def _teardown():
    at.reset_terminals()


def test_two_sessions_same_agent_no_overwrite():
    """P0.2: the second session must never steal the first's binding."""
    _setup()
    try:
        r1 = register_session("sess-1", "agent-a")
        r2 = register_session("sess-2", "agent-a")
        assert r1["success"] is True and r2["success"] is True
        g1, g2 = get_session("sess-1"), get_session("sess-2")
        assert g1["success"] and g2["success"]
        assert g1["state"] == g2["state"] == "active"
        # primary binding stays the first session; set holds both
        t = at.get_terminal("agent-a")
        assert t.session_id == "sess-1"
        assert t._bound_sessions == {"sess-1", "sess-2"}
    finally:
        _teardown()


def test_register_meta_preserved():
    """P0.2: user_id/role/cell_id/memory_scope ride on the record."""
    _setup()
    try:
        register_session(
            "sess-m",
            "agent-m",
            meta={"user_id": "u1", "memory_scope": "l3a-c-7", "cell_id": "cell-1", "role": "peer"},
        )
        rec = get_session("sess-m")
        assert rec["meta"] == {"user_id": "u1", "memory_scope": "l3a-c-7", "cell_id": "cell-1", "role": "peer"}
        assert rec["state"] == "active"
    finally:
        _teardown()


def test_detach_marks_and_releases_slot():
    """P0.2: detach keeps history but frees the terminal slot."""
    _setup()
    try:
        register_session("sess-d", "agent-d")
        t = at.get_terminal("agent-d")
        assert t._bound_sessions == {"sess-d"}
        r = detach_session("sess-d")
        assert r["success"] is True
        assert t._bound_sessions == set()
        assert t.session_id == ""
        assert get_session("sess-d")["state"] == "detached"
        assert close_session_binding("sess-d") is True  # detached may still close
    finally:
        _teardown()


def test_close_binding_releases_slot_once():
    """P0.2: close is idempotent and hides closed rows by default."""
    _setup()
    try:
        register_session("sess-c", "agent-c")
        assert close_session_binding("sess-c") is True
        assert close_session_binding("sess-c") is False
        t = at.get_terminal("agent-c")
        assert t._bound_sessions == set()
        rows = list_sessions()
        assert all(r["session_id"] != "sess-c" for r in rows["sessions"])
        closed = list_sessions(include_closed=True)
        assert any(r["session_id"] == "sess-c" for r in closed["sessions"])
    finally:
        _teardown()


def test_auto_reload_rebuilds_workers():
    """P0.3: a healthy reload restores a reachable worker pool."""
    _setup()
    try:
        t = AgentTerminal("agent-r", cell_id="cell-r")
        r = t.auto_reload(reason="test")
        assert r["success"] is True
        assert r["status"] == "IDLE"
        assert r["workers"] == t._max_workers
        assert t._running is True
        assert len(t._workers) == t._max_workers
        assert t.session_reachable()["reachable"] is True
        t.shutdown()
    finally:
        _teardown()


def test_auto_reload_fails_loud_on_stuck_worker(monkeypatch):
    """P0.3: a worker that ignores the join deadline blocks the reload — no fake IDLE."""
    _setup()
    try:
        monkeypatch.setattr(at, "AGENT_TERMINAL_WORKER_JOIN_TIMEOUT", 0.2)
        t = AgentTerminal("agent-s", cell_id="cell-s")
        stuck = threading.Thread(target=lambda: threading.Event().wait(5), daemon=True)
        stuck.start()
        t._workers = [stuck]
        r = t.auto_reload(reason="stagnation:SPINNING")
        assert r["success"] is False
        assert r["status"] == "BLOCKED"
        assert stuck.name in r["stuck_workers"][0] or len(r["stuck_workers"]) == 1
        assert t.status.name == "BLOCKED"
    finally:
        _teardown()


def test_session_manager_close_releases_binding():
    """P0.2: SessionManager.close releases the terminal slot end-to-end."""
    from l3.cell.peers.l3a.session import SessionManager

    _setup()
    try:
        mgr = SessionManager()
        s = mgr.create(title="identity probe")
        t = at.get_terminal(at_params_agent_id())
        assert s.id in t._bound_sessions
        mgr.close(s.id)
        assert s.id not in t._bound_sessions
        assert get_session(s.id)["state"] == "closed"
    finally:
        _teardown()


def at_params_agent_id() -> str:
    """Return the L3A AGENT_ID used by Session.__init__ bindings."""
    from l3.cell.peers.l3a import params as _p

    return _p.AGENT_ID


def test_process_id_pinned_per_terminal():
    """Dual identity: process_id pins the backing OS process."""
    t = AgentTerminal("agent-pid-2", cell_id="cell-x")
    assert t.process_id == os.getpid()
