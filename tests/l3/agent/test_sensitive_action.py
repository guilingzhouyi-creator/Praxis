"""Sensitive-info action policy tests (3.1, G6): report / redact / block."""

from __future__ import annotations


def test_redact_text_masks_sensitive_patterns():
    from l3.agent.sensitive_detect import redact_text, reset_sensitive

    reset_sensitive()
    try:
        text = "use the key sk-abcdefghijklmnopqrstuvwxyz and 10.0.0.1"
        redacted = redact_text(text)
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in redacted
        assert "[REDACTED:api_key]" in redacted
        assert "10.0.0.1" not in redacted
    finally:
        reset_sensitive()


def test_action_switch_persists_and_reset():
    from l3.agent.sensitive_detect import reset_sensitive, sensitive_status, set_sensitive_switches

    reset_sensitive()
    try:
        assert sensitive_status()["action"] == "report"
        set_sensitive_switches(action="redact")
        assert sensitive_status()["action"] == "redact"
        reset_sensitive()
        assert sensitive_status()["action"] == "report"
    finally:
        reset_sensitive()


def test_invalid_action_rejected():
    from l3.agent.sensitive_detect import reset_sensitive, set_sensitive_switches

    reset_sensitive()
    try:
        r = set_sensitive_switches(action="bogus")
        assert r.get("success") is False
    finally:
        reset_sensitive()


def test_compress_redact_action_masks_summary():
    from l3.agent.sensitive_detect import reset_sensitive, set_sensitive_switches
    from l3.cell.peers.l3a.session import Message, Session

    reset_sensitive()
    try:
        set_sensitive_switches(action="redact")
        s = Session.create(title="redact-test")
        s.history.append(Message(id="u0", role="user", content="use key sk-abcdefghijklmnopqrstuvwxyz"))
        s.history.append(Message(id="a0", role="assistant", content="ok " + "x" * 60))
        r = s.compress(keep_last=1)
        assert r.get("success") is True
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in r.get("summary", "")
        assert "[REDACTED:api_key]" in r.get("summary", "")
    finally:
        reset_sensitive()


def test_compress_block_action_refuses_fold():
    from l3.agent.sensitive_detect import reset_sensitive, set_sensitive_switches
    from l3.cell.peers.l3a.session import Message, Session

    reset_sensitive()
    try:
        set_sensitive_switches(action="block")
        s = Session.create(title="block-test")
        s.history.append(Message(id="u0", role="user", content="use key sk-abcdefghijklmnopqrstuvwxyz"))
        s.history.append(Message(id="a0", role="assistant", content="ok " + "x" * 60))
        r = s.compress(keep_last=1)
        assert r.get("success") is False
        assert "block" in r.get("error", "")
    finally:
        reset_sensitive()
