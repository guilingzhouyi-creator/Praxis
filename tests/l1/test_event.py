"""Tests for EventBus — Signal, SignalType, publish/subscribe, history."""

from __future__ import annotations

from l1.kernel.event import (
    EventBus,
    Signal,
    SignalType,
    get_bus,
    register_signal_type,
    reset_bus,
)


def test_signal_defaults() -> None:
    s = Signal(type=SignalType.TASK_ASSIGN)
    assert s.type == SignalType.TASK_ASSIGN
    assert s.data == {}
    assert s.sender == ""
    assert s.target == ""
    assert s.timestamp > 0


def test_signal_to_dict() -> None:
    s = Signal(type=SignalType.TASK_DONE, data={"result": "ok"}, sender="agent-1")
    d = s.to_dict()
    assert d["type"] == "TASK_DONE"
    assert d["data"] == {"result": "ok"}
    assert d["sender"] == "agent-1"


def test_emit_returns_callback_count() -> None:
    bus = EventBus(max_history=10)

    def cb(s):
        return None

    bus.on(SignalType.TASK_ASSIGN, cb)
    sig = Signal(type=SignalType.TASK_ASSIGN)
    count = bus.emit(sig)
    assert count == 1


def test_emit_wildcard_counted() -> None:
    bus = EventBus(max_history=10)
    bus.on_any(lambda s: None)
    count = bus.emit(Signal(type=SignalType.CONSTITUTION_UPDATE))
    assert count == 1


def test_listener_called() -> None:
    bus = EventBus(max_history=10)
    results: list[Signal] = []
    bus.on(SignalType.TASK_DONE, lambda s: results.append(s))
    bus.emit(Signal(type=SignalType.TASK_DONE, data={"id": "card-1"}))
    bus._executor.shutdown(wait=True)
    assert len(results) == 1
    assert results[0].data["id"] == "card-1"


def test_wildcard_listener_receives_all() -> None:
    bus = EventBus(max_history=10)
    received: list[str] = []
    bus.on_any(lambda s: received.append(s.type.name))
    bus.emit(Signal(type=SignalType.AGENT_CRASH))
    bus.emit(Signal(type=SignalType.SCOUT_DONE))
    bus._executor.shutdown(wait=True)
    assert "AGENT_CRASH" in received
    assert "SCOUT_DONE" in received


def test_listener_not_called_for_different_type() -> None:
    bus = EventBus(max_history=10)
    bus.on(SignalType.TASK_CANCEL, lambda s: None)
    bus.emit(Signal(type=SignalType.TASK_DONE))
    bus._executor.shutdown(wait=True)
    # We just verify no crash; callback for wrong type should not fire


def test_off_removes_listener() -> None:
    bus = EventBus(max_history=10)
    calls = []

    def cb(s):
        calls.append(s)

    bus.on(SignalType.REVIEW_RESULT, cb)
    bus.off(SignalType.REVIEW_RESULT, cb)
    bus.emit(Signal(type=SignalType.REVIEW_RESULT))
    bus._executor.shutdown(wait=True)
    assert len(calls) == 0


def test_off_removes_all_for_type() -> None:
    bus = EventBus(max_history=10)
    bus.on(SignalType.STATE_CHANGE, lambda s: None)
    bus.on(SignalType.STATE_CHANGE, lambda s: None)
    bus.off(SignalType.STATE_CHANGE)  # remove all
    count = bus.emit(Signal(type=SignalType.STATE_CHANGE))
    assert count == 0


def test_on_any_not_removed_by_off_type() -> None:
    bus = EventBus(max_history=10)
    calls = []
    bus.on_any(lambda s: calls.append(s))
    bus.off(SignalType.TASK_ASSIGN)  # should NOT affect wildcard
    bus.emit(Signal(type=SignalType.TASK_ASSIGN))
    bus._executor.shutdown(wait=True)
    assert len(calls) == 1


def test_off_any_removes_wildcard_listener() -> None:
    """off_any removes exactly the wildcard callback registered by on_any."""
    bus = EventBus(max_history=10)
    calls = []

    def cb(signal: Signal) -> None:
        calls.append(signal)

    bus.on_any(cb)
    bus.off_any(cb)
    assert bus.stats()["wildcard_listeners"] == 0
    bus.emit(Signal(type=SignalType.TASK_ASSIGN))
    bus.shutdown(wait=True, timeout=1.0)
    assert calls == []


def test_history_records_emitted_signals() -> None:
    bus = EventBus(max_history=5)
    bus.emit(Signal(type=SignalType.TASK_ASSIGN))
    bus.emit(Signal(type=SignalType.TASK_DONE))
    h = bus.history()
    assert len(h) == 2
    assert h[0]["type"] == "TASK_ASSIGN"
    assert h[1]["type"] == "TASK_DONE"


def test_history_filtered_by_type() -> None:
    bus = EventBus(max_history=10)
    bus.emit(Signal(type=SignalType.SCOUT_DONE))
    bus.emit(Signal(type=SignalType.TASK_ASSIGN))
    h = bus.history(signal_type=SignalType.SCOUT_DONE)
    assert len(h) == 1
    assert h[0]["type"] == "SCOUT_DONE"


def test_history_respects_limit() -> None:
    bus = EventBus(max_history=50)
    for i in range(10):
        bus.emit(Signal(type=SignalType.TASK_ASSIGN, data={"n": i}))
    h = bus.history(limit=3)
    assert len(h) == 3
    assert h[-1]["data"]["n"] == 9


def test_stats() -> None:
    bus = EventBus(max_history=10)
    bus.on(SignalType.TASK_DONE, lambda s: None)
    bus.on(SignalType.AGENT_CRASH, lambda s: None)
    bus.on_any(lambda s: None)
    s = bus.stats()
    assert s["signal_types"] == 2
    assert s["listeners"] == 2  # typed listeners only; wildcard is separate
    assert s["history"] == 0
    assert s["wildcard_listeners"] == 1
    assert s["submitted"] == 0
    assert s["completed"] == 0
    assert s["dropped"] == 0
    assert s["drop_rate"] == 0.0


def test_stats_count_successful_dispatches() -> None:
    """Successful executor submissions become completed after a draining shutdown."""
    bus = EventBus(max_history=10)
    bus.on_any(lambda _signal: None)
    assert bus.emit(Signal(type=SignalType.TASK_DONE)) == 1
    bus.shutdown(wait=True, timeout=1.0)
    stats = bus.stats()
    assert stats["submitted"] == 1
    assert stats["completed"] == 1
    assert stats["dropped"] == 0
    assert stats["queue_depth"] == 0


def test_stats_count_queue_drops() -> None:
    """A full bounded queue increments dropped without leaking in-flight work."""
    bus = EventBus(max_history=10)
    bus._MAX_EVT_QUEUED = 0
    bus.on_any(lambda _signal: None)
    assert bus.emit(Signal(type=SignalType.TASK_DONE)) == 1
    stats = bus.stats()
    assert stats["submitted"] == 0
    assert stats["completed"] == 0
    assert stats["dropped"] == 1
    assert stats["queue_depth"] == 0
    assert stats["drop_rate"] == 1.0
    bus.shutdown(wait=True, timeout=1.0)


def test_stats_count_executor_submit_failure() -> None:
    """Executor submission failure releases the reservation and counts one drop."""

    class FailingExecutor:
        """Minimal executor double that rejects every submission."""

        def submit(self, *_args, **_kwargs):
            raise RuntimeError("executor closed")

        def shutdown(self, **_kwargs):
            return None

    bus = EventBus(max_history=10)
    bus._executor = FailingExecutor()
    bus.on_any(lambda _signal: None)
    assert bus.emit(Signal(type=SignalType.TASK_DONE)) == 1
    stats = bus.stats()
    assert stats["submitted"] == 0
    assert stats["completed"] == 0
    assert stats["dropped"] == 1
    assert stats["queue_depth"] == 0
    bus.shutdown(wait=True, timeout=1.0)


def test_shutdown_idempotent() -> None:
    bus = EventBus(max_history=10)
    bus.shutdown()
    bus.shutdown()  # should not raise


def test_emit_after_shutdown_synchronous() -> None:
    bus = EventBus(max_history=5)
    results: list[str] = []
    bus.on(SignalType.TASK_DONE, lambda s: results.append("called"))
    bus.shutdown()
    bus.emit(Signal(type=SignalType.TASK_DONE))
    assert len(results) == 1


def test_string_based_emit_event() -> None:
    bus = EventBus(max_history=10)
    results: list[str] = []
    bus.on_event("CUSTOM_EVENT", lambda s: results.append(s.type.name))
    bus.emit_event("CUSTOM_EVENT", data={"key": "val"}, source="test")
    bus._executor.shutdown(wait=True)
    assert "CUSTOM_EVENT" in results


def test_register_signal_type_dynamic() -> None:
    st = register_signal_type("MY_TYPE")
    assert st.name == "MY_TYPE"
    # Calling again returns cached
    assert register_signal_type("MY_TYPE") is st


def test_register_builtin_type_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        register_signal_type("TASK_ASSIGN")


def test_register_signal_type_capped(monkeypatch) -> None:
    """The runtime signal-type registry is capped (memory bound)."""
    import pytest

    import l1.kernel.event as ev_mod

    # Registry is a module-level singleton — isolate from earlier tests
    monkeypatch.setattr(ev_mod, "_SIGNAL_TYPE_REGISTRY", {})
    monkeypatch.setattr(ev_mod, "SIGNAL_TYPE_REGISTRY_MAX", 2)
    register_signal_type("CAP_TYPE_1")
    register_signal_type("CAP_TYPE_2")
    with pytest.raises(ValueError):
        register_signal_type("CAP_TYPE_3")
    # Existing types remain resolvable
    assert register_signal_type("CAP_TYPE_1").name == "CAP_TYPE_1"


def test_emit_event_degrades_when_registry_full(monkeypatch) -> None:
    """emit_event/on_event must not crash once the registry is full."""
    import l1.kernel.event as ev_mod

    monkeypatch.setattr(ev_mod, "_SIGNAL_TYPE_REGISTRY", {})
    monkeypatch.setattr(ev_mod, "SIGNAL_TYPE_REGISTRY_MAX", 1)
    bus = EventBus()
    # One slot used; a second distinct type must degrade, not raise
    assert bus.emit_event("DEGRADE_1", {"k": 1}) >= 0
    assert bus.emit_event("DEGRADE_2", {"k": 2}) == 0  # dropped
    # Subscription also degrades instead of raising
    bus.on_event("DEGRADE_3", lambda s: None)  # must not raise


def test_get_bus_returns_singleton() -> None:
    b1 = get_bus()
    b2 = get_bus()
    assert b1 is b2


def test_reset_bus_creates_new() -> None:
    b1 = get_bus()
    reset_bus()
    b2 = get_bus()
    assert b1 is not b2


def test_reset_bus_drains_executor_threads() -> None:
    """reset_bus() must wait for the old executor's non-daemon threads to exit."""
    import threading
    import time

    bus = EventBus()
    bus.on(SignalType.STATE_CHANGE, lambda s: None)
    for _ in range(20):
        bus.emit(Signal(type=SignalType.STATE_CHANGE, data={}))
    time.sleep(0.1)
    evt_threads = [t for t in threading.enumerate() if t.name.startswith("evt")]
    assert evt_threads, "executor thread should exist after emit"
    bus.shutdown(wait=True, timeout=5.0)
    time.sleep(0.1)
    alive = [t for t in threading.enumerate() if t.name.startswith("evt")]
    assert not alive, "executor threads must exit after shutdown(wait=True)"


def test_history_from_empty() -> None:
    bus = EventBus(max_history=5)
    assert bus.history() == []


def test_emit_with_callback_error_does_not_crash() -> None:
    bus = EventBus(max_history=5)

    def broken(signal: Signal) -> None:
        raise RuntimeError("oops")

    bus.on(SignalType.TASK_DONE, broken)
    bus.emit(Signal(type=SignalType.TASK_DONE))
    bus._executor.shutdown(wait=True)
    # No crash = pass
