"""Compression-ratio baseline tests (Phase 3.1, B3).

Verifies that ``session_compress`` reports a meaningful ``compression_ratio``
(before/after token counts) so the operator has a performance baseline for
how much a folded span shrank. Guarded against divide-by-zero on empty
summaries.
"""

from __future__ import annotations


def _session_with_messages(n: int):
    """Create a Session and inject n user/assistant message pairs."""
    from l3.cell.peers.l3a.session import Message, Session

    s = Session.create(title="ratio-test")
    for i in range(n):
        s.history.append(
            Message(id=f"u{i}", role="user", content=f"user message number {i} with enough text to matter")
        )
        s.history.append(Message(id=f"a{i}", role="assistant", content=f"assistant reply {i} " + "x" * 60))
    return s


def test_compress_reports_ratio():
    """compress returns a compression_ratio > 1 when a span is folded."""
    s = _session_with_messages(20)
    r = s.compress(keep_last=4)
    assert r.get("success") is True
    assert r["compressed"] > 0
    assert r["before_tokens"] > r["after_tokens"]
    assert r["compression_ratio"] > 1.0


def test_compress_ratio_matches_token_counts():
    """ratio == round(before/after, 2) — the performance baseline."""
    s = _session_with_messages(20)
    r = s.compress(keep_last=4)
    expected = round(r["before_tokens"] / r["after_tokens"], 2) if r["after_tokens"] > 0 else 0.0
    assert r["compression_ratio"] == expected


def test_nothing_to_compress_ratio_zero():
    """No folding → ratio 0.0 (guard against divide-by-zero)."""
    s = _session_with_messages(2)
    r = s.compress(keep_last=4)
    assert r.get("compressed") == 0
    assert r.get("compression_ratio") == 0.0


def test_dedup_collapses_repeated_user_messages():
    """B4: identical user messages in the folded span collapse to one."""
    from l3.cell.peers.l3a.session import Message, Session

    s = Session.create(title="dedup-test")
    for i in range(3):
        s.history.append(Message(id=f"u{i}", role="user", content="同一个重复请求"))
    s.history.append(Message(id="u3", role="user", content="不同的请求"))
    for i in range(4):
        s.history.append(Message(id=f"a{i}", role="assistant", content="reply " + "x" * 40))
    r = s.compress(keep_last=2)
    assert r["deduplicated"] == 2  # two of the three repeats dropped


def test_five_level_pipeline_reports_levels():
    """B5: compress reports the five-level pipeline stats."""
    from l3.cell.peers.l3a.session import Message, Session

    s = Session.create(title="five-level")
    msgs = [
        Message(id="u0", role="user", content="最早意图：初始化项目"),
        Message(id="a0", role="assistant", content="开始搭建 " + "x" * 50),
        Message(id="u1", role="user", content="中等请求：配置构建"),
        Message(id="a1", role="assistant", content="已配置 " + "y" * 50),
        Message(id="u2", role="user", content="近期请求"),
        Message(id="a2", role="assistant", content="reply " + "w" * 40),
    ]
    for m in msgs:
        s.history.append(m)
    r = s.compress(keep_last=2)
    levels = r.get("levels", {})
    assert levels.get("raw", 0) >= 1
    assert levels.get("retained") == 2
    assert "HEADLINE" in (r.get("summary") or "")


def test_compress_reports_sensitive_hits():
    """B6: a folded summary containing an API key surfaces sensitive_hits."""
    from l3.agent.sensitive_detect import reset_sensitive
    from l3.cell.peers.l3a.session import Message, Session

    reset_sensitive()
    try:
        s = Session.create(title="sensitive-test")
        msgs = [
            Message(id="u0", role="user", content="use the key sk-abcdefghijklmnopqrstuvwxyz to connect"),
            Message(id="a0", role="assistant", content="configured endpoint " + "x" * 60),
        ]
        for m in msgs:
            s.history.append(m)
        r = s.compress(keep_last=1)
        hits = r.get("sensitive_hits", [])
        assert any(h.get("kind") == "api_key" for h in hits)
    finally:
        reset_sensitive()


def test_compress_blocked_by_guard_threshold():
    """B6: a tripped compression guard blocks the fold before it happens."""
    from l3.agent.compression_guard import (
        record_compress_pass,
        reset_guard,
        set_guard_switches,
    )
    from l3.cell.peers.l3a.session import Message, Session

    reset_guard()
    try:
        set_guard_switches(recursion_threshold=1)
        s = Session.create(title="guard-test")
        for i in range(4):
            s.history.append(Message(id=f"u{i}", role="user", content=f"message number {i} with text"))
        # Pass 1 allowed; the recorded pass trips the breaker for pass 2.
        record_compress_pass(str(s.id))
        r = s.compress(keep_last=2)
        assert r.get("success") is False
        assert "threshold" in r.get("error", "")
    finally:
        reset_guard()
