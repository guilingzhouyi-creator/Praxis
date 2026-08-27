"""Tests for l3b_bus.py — L3B communication bus."""

from __future__ import annotations

from l3.bus.l3b_bus import L3BMessageType, get_bus, reset_bus


def setup_method():
    reset_bus()


def test_bus_register():
    """A composite can be registered on the bus."""
    reset_bus()
    bus = get_bus()
    r = bus.register("l3b-test-a-b")
    assert r["success"]
    assert "l3b-test-a-b" in r["composite_id"]


def test_bus_send_adjacent():
    """Adjacent composites can communicate directly."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    bus.register("l3b-cell-2-cell-3")
    r = bus.send("l3b-cell-1-cell-2", "l3b-cell-2-cell-3", L3BMessageType.HEARTBEAT, {"ping": True})
    assert r["success"]


def test_bus_read():
    """Reading from a mailbox returns sent messages."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    bus.send("l3b-cell-1-cell-2", "l3b-cell-1-cell-2", L3BMessageType.CARD_FORWARD, {"task": "test"})
    msgs = bus.read("l3b-cell-1-cell-2", limit=5)
    assert len(msgs) >= 1
    assert msgs[0]["msg_type"] == "CARD_FORWARD"


def test_bus_stats():
    """Bus has readable statistics."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-test-x-y")
    stats = bus.stats()
    assert "registered_composites" in stats
    assert stats["registered_composites"] >= 1


# ── 2.1: auto-routed Cell-to-Cell topology (route_to_cell) ──


def test_route_to_cell_direct():
    """A composite already reaching the target Cell routes directly."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    r = bus.route_to_cell(
        "", "cell-2", L3BMessageType.REVIEW_REWORK, {"rel_path": "systems/python-reference-runtime/a.py"}
    )
    assert r["success"] is True
    assert r["path"] == ["l3b-cell-1-cell-2"]
    assert r["hops"] == 0
    msgs = bus.read("l3b-cell-1-cell-2", limit=5)
    assert msgs and msgs[0]["msg_type"] == "REVIEW_REWORK"


def test_route_to_cell_multi_hop_bfs():
    """With 3+ Cells the shortest channel is found via BFS and delivered hop-by-hop."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    bus.register("l3b-cell-2-cell-3")
    bus.register("l3b-cell-3-cell-4")
    r = bus.route_to_cell("l3b-cell-1-cell-2", "cell-4", L3BMessageType.REVIEW_REWORK, {"x": 1})
    assert r["success"] is True
    # Shortest path cell-1→cell-4 crosses both composites (2 hops).
    assert r["hops"] == 2
    assert r["path"][0] == "l3b-cell-1-cell-2"
    assert r["path"][-1] == "l3b-cell-3-cell-4"
    # Every composite on the path received a hop.
    for cid in r["path"]:
        msgs = bus.read(cid, limit=5)
        assert msgs, f"{cid} should have received a hop"


def test_route_to_cell_unreachable():
    """No composite reaches the target Cell → graceful error, no raise."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-cell-1-cell-2")
    r = bus.route_to_cell("", "cell-99", L3BMessageType.REVIEW_REWORK, {})
    assert r["success"] is False
    assert "error" in r


def test_route_to_cell_no_composites():
    """No registered composites → graceful error (single-Cell mode)."""
    reset_bus()
    bus = get_bus()
    r = bus.route_to_cell("", "cell-1", L3BMessageType.REVIEW_REWORK, {})
    assert r["success"] is False


def test_bus_send_backpressure():
    """BACKPRESSURE signal can be sent between composites."""
    reset_bus()
    bus = get_bus()
    bus.register("l3b-a-b")
    bus.register("l3b-b-c")
    r = bus.send_backpressure("l3b-a-b", "l3b-b-c", reason="queue full")
    assert r["success"]
