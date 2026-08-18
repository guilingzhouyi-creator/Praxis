"""RC data-analysis closure tests for L3A compression events (3.1, G5).

Verifies the compression / tool-offload / digest paths emit structured
events to the ReferenceChannel so RecordCenter can aggregate them for
downstream analysis.
"""

from __future__ import annotations


def test_compress_emits_rc_event():
    from l3.bus.reference_channel import get_rc, reset_rc
    from l3.cell.peers.l3a.session import Message, Session

    reset_rc()
    try:
        s = Session.create(title="rc-test")
        for i in range(6):
            s.history.append(Message(id=f"u{i}", role="user", content=f"message {i} with text"))
            s.history.append(Message(id=f"a{i}", role="assistant", content="reply " + "x" * 40))
        rc = get_rc()
        before = rc.stats()["total_events"]
        r = s.compress(keep_last=2)
        assert r.get("success") is True
        assert rc.stats()["total_events"] > before
        rc.flush()
        assert len(rc.export(event_type="l3a_compress")) >= 1
    finally:
        reset_rc()


def test_offload_emits_rc_event():
    from l3.agent.tool_result_cache import maybe_offload, reset_tool_result
    from l3.bus.reference_channel import get_rc, reset_rc

    reset_tool_result()
    reset_rc()
    try:
        rc = get_rc()
        before = rc.stats()["total_events"]
        result = maybe_offload("cell1", "call1", "big_tool", {"data": "x" * 5000})
        assert result.get("offloaded") is True
        assert rc.stats()["total_events"] > before
        rc.flush()
        assert len(rc.export(event_type="l3a_tool_offload")) >= 1
    finally:
        reset_tool_result()
        reset_rc()


def test_digest_emits_rc_event():
    from l3.agent.digest_cache import fold_messages, reset_digest, set_digest_switches
    from l3.bus.reference_channel import get_rc, reset_rc

    reset_digest()
    reset_rc()
    try:
        set_digest_switches(enabled=True)
        rc = get_rc()
        before = rc.stats()["total_events"]
        digest = fold_messages("cell1", "card1", [{"role": "user", "content": "hello world"}])
        assert digest
        assert rc.stats()["total_events"] > before
        rc.flush()
        assert len(rc.export(event_type="l3a_digest")) >= 1
    finally:
        reset_digest()
        reset_rc()
