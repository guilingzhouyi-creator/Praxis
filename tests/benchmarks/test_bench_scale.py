"""Unit coverage for fixed-work Amdahl benchmark calculations and CLI wiring."""

from __future__ import annotations

import pytest

from l4.params import EVAL_AMDAHL_TOTAL_WORK_ITEMS
from tests.benchmarks import bench_scale


def test_split_fixed_work_preserves_total_and_balances_partitions() -> None:
    """Fixed work allocation keeps the total constant across a worker sweep."""
    partitions = bench_scale._split_fixed_work(10, 3)

    assert partitions == [4, 3, 3]
    assert sum(partitions) == 10
    assert max(partitions) - min(partitions) == 1


def test_split_fixed_work_rejects_impossible_worker_count() -> None:
    """Every measured worker must receive at least one work item."""
    with pytest.raises(ValueError, match="work items"):
        bench_scale._split_fixed_work(3, 4)


def test_percentile_uses_nearest_rank() -> None:
    """High percentiles select the correct tail rank for short samples."""
    assert bench_scale._percentile([1.0, 2.0], 0.95) == 2.0


def test_amdahl_fit_reports_serial_fraction_not_parallel_fraction() -> None:
    """Known Amdahl timings recover the serial fraction used by the verdict."""
    agent_counts = [1, 2, 4]
    wall_times = [1.0, 0.625, 0.4375]

    assert bench_scale._fit_serial_fraction(agent_counts, wall_times) == pytest.approx(0.25)
    assert bench_scale._amdahl_speedup(0.25, 4) == pytest.approx(2.2857142857)


def test_l1_amdahl_round_reports_exact_fixed_work_and_latency_metrics() -> None:
    """A small real L1 sweep completes the same work for every worker count."""
    report = bench_scale.run_amdahl_l1([1, 2], total_work_items=16, rounds=1)

    assert report["agent_counts"] == [1, 2]
    assert report["fixed_total_work_items"] == 16
    assert report["completed_work_items"] == [16, 16]
    assert len(report["throughput_ops_per_sec"]) == 2
    assert len(report["operation_latency_p95_ms"]) == 2
    assert len(report["queue_wait_p95_ms"]) == 2
    assert len(report["lock_wait_p95_ms"]) == 2


def test_lock_contention_uses_fixed_total_work_per_worker_count() -> None:
    """Lock contention samples do not multiply their operation count by workers."""
    report = bench_scale.run_lock_contention([1, 2, 4], total_work_items=16, rounds=1)

    for curve in report.values():
        assert [point["fixed_total_work_items"] for point in curve.values()] == [16, 16, 16]
        assert all("lock_wait_p95_ms" in point for point in curve.values())


def test_event_benchmark_isolates_listeners_and_records_delivery() -> None:
    """Each EventBus round drains its local listeners and reports delivery counts."""
    report = bench_scale.run_queue_event(queue_iters=2, event_iters=3, listener_counts=[0, 1], rounds=2)

    zero = report["event_bus"]["0"]
    one = report["event_bus"]["1"]
    assert len(zero["rounds"]) == 2
    assert len(one["rounds"]) == 2
    assert zero["clean"] is True
    assert one["clean"] is True
    assert one["submitted"] == 6
    assert one["completed"] == 6
    assert one["dropped"] == 0
    assert one["queue_depth"] == 0
    assert one["drained"] is True
    assert all(sample["submitted"] == 3 for sample in one["rounds"])
    assert all(sample["completed"] == 3 for sample in one["rounds"])


def test_event_benchmark_can_record_bounded_clean_curve() -> None:
    """A bounded load curve provides a clean delivery comparison beside overload data."""
    report = bench_scale.run_queue_event(
        queue_iters=2,
        event_iters=3,
        listener_counts=[0, 1],
        rounds=2,
        bounded_event_iters=2,
    )

    bounded = report["bounded_event_bus"]
    assert bounded["1"]["clean"] is True
    assert bounded["1"]["drained"] is True
    assert bounded["1"]["submitted"] == 4
    assert bounded["1"]["completed"] == 4
    assert bounded["1"]["dropped"] == 0


def test_mutex_contention_assigns_a_distinct_identity_per_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutex contention cannot collapse into same-agent recursive acquisitions."""
    from l1.kernel import sync
    from l1.kernel.params.sync import MUTEX_DEFAULT_PRIORITY

    seen_agent_ids: set[str] = set()
    original_mutex = sync.Mutex

    class RecordingMutex(original_mutex):
        """Record each identity passed to the real Mutex acquisition path."""

        def acquire(self, agent_id: str, priority: float = MUTEX_DEFAULT_PRIORITY, blocking: bool = True) -> dict:
            seen_agent_ids.add(agent_id)
            return super().acquire(agent_id, priority, blocking)

    monkeypatch.setattr(sync, "Mutex", RecordingMutex)

    result = bench_scale._contended_mutex_ops(workers=2, total_work_items=4)

    assert result["completed_work_items"] == 4
    assert seen_agent_ids == {"lock-bench-agent-0", "lock-bench-agent-1"}


def test_main_passes_requested_agents_to_l1_amdahl(monkeypatch: pytest.MonkeyPatch) -> None:
    """The --agents option controls the executed L1 worker-count sweep."""
    calls: list[tuple[list[int], int, int]] = []

    def _fake_run(agent_counts: list[int], total_work_items: int, rounds: int) -> dict[str, object]:
        calls.append((agent_counts, total_work_items, rounds))
        return {}

    monkeypatch.setattr(bench_scale, "run_amdahl_l1", _fake_run)
    monkeypatch.setattr(bench_scale, "print_report", lambda _platform, _report: None)
    monkeypatch.setattr(
        bench_scale.sys,
        "argv",
        ["bench_scale.py", "--mode", "amdahl", "--agents", "1,3", "--rounds", "2"],
    )

    assert bench_scale.main() == 0
    assert calls == [([1, 3], EVAL_AMDAHL_TOTAL_WORK_ITEMS, 2)]


def test_parse_agent_counts_rejects_non_baseline_sweep() -> None:
    """An Amdahl fit requires an unambiguous one-worker baseline."""
    with pytest.raises(ValueError, match="starting with 1"):
        bench_scale._parse_agent_counts("2,4")
