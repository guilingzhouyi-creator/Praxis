"""Web endpoint protocol v1 mode: /shell accepts protocol envelopes.

The legacy ``{text, session}`` dict mode stays; envelope mode routes
through the shared ProtocolHost so web clients reuse the same session
semantics as the TS bridge.
"""

from __future__ import annotations

from l2.protocol import KIND_ACK, KIND_COMMAND, KIND_CONTROL, KIND_EVENT, KIND_INTENT, KIND_RESULT, make_message
from l2.protocol.host import get_protocol_host, reset_protocol_host
from l4.api_handlers.api_handlers_agent import _shell_dispatch


def _command(name: str, session_id: str = "s-web-1", seq: int = 1) -> dict:
    return make_message(session_id, seq, KIND_COMMAND, {"name": name, "args": []})


def test_protocol_envelope_mode_returns_result_and_ack():
    reset_protocol_host()
    out = _shell_dispatch(_command("help"))
    assert out["success"] is True
    kinds = [env["kind"] for env in out["envelopes"]]
    assert KIND_RESULT in kinds
    assert KIND_ACK in kinds


def test_protocol_intent_routes_through_dispatch():
    reset_protocol_host()
    msg = make_message("s-web-2", 1, KIND_INTENT, {"text": "help"})
    out = _shell_dispatch(msg)
    assert out["success"] is True
    result = next(env for env in out["envelopes"] if env["kind"] == KIND_RESULT)
    # Intent routes into the L3A path; in a bare test host the L3 runtime is
    # unavailable, so the result must at least be a structured dict carrying
    # success (True or False) — the routing itself is what is pinned here.
    assert isinstance(result["payload"], dict)
    assert "success" in result["payload"]


def test_legacy_dict_mode_unchanged():
    out = _shell_dispatch({"text": "/help"})
    assert out.get("success") is True


def test_invalid_envelope_fails_closed():
    reset_protocol_host()
    out = _shell_dispatch({"kind": "nope"})
    # Outer success means the protocol layer handled the request; the
    # validation failure is carried inside the result envelope.
    assert out["success"] is True
    result = next(env for env in out["envelopes"] if env["kind"] == KIND_RESULT)
    assert result["payload"]["success"] is False


def test_web_mode_reuses_host_session_pool():
    reset_protocol_host()
    host = get_protocol_host()
    _shell_dispatch(make_message("s-pool", 1, KIND_INTENT, {"text": "help"}))
    _shell_dispatch(make_message("s-pool", 2, KIND_INTENT, {"text": "status"}))
    assert "s-pool" in host._sessions
    assert len(host._sessions) == 1


def test_attach_emits_session_identity_snapshot():
    reset_protocol_host()
    msg = make_message("s-attach", 1, KIND_CONTROL, {"op": "attach", "session_id": "s-attach"})
    out = _shell_dispatch(msg)
    event = next(env for env in out["envelopes"] if env["kind"] == KIND_EVENT)
    assert event["payload"]["name"] == "session.attached"
    identity = event["payload"]["data"]
    assert identity["session_id"] == "s-attach"
    # The SessionIdentity wire record is fully present (TS-mirrored shape).
    for field in ("terminal_id", "process_id", "user_id", "role", "cell_id", "memory_scope"):
        assert field in identity
