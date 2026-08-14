"""Tests for LoadAdaptiveController — pure-function unit tests.

All tests are millisecond-level; no threads, no I/O, no network.
"""

from __future__ import annotations

import pytest

from l1.kernel.load_adaptive import (
    Action,
    ControllerMetrics,
    LoadAdaptiveController,
)


def _metrics(
    queue_ratio: float = 0.0,
    worker_count: int = 4,
    worker_min: int = 4,
    worker_max: int = 32,
    task_elapsed: float = 0.0,
) -> ControllerMetrics:
    return ControllerMetrics(
        queue_ratio=queue_ratio,
        worker_count=worker_count,
        worker_min=worker_min,
        worker_max=worker_max,
        task_elapsed=task_elapsed,
    )


# ── Initialisation ────────────────────────────────────────────────────────


class TestInit:
    def test_default_params(self) -> None:
        c = LoadAdaptiveController()
        s = c.state()
        assert s["low_ratio"] == 0.2
        assert s["high_ratio"] == 0.6
        assert s["ewma_alpha"] == 0.3
        assert s["hysteresis_samples"] == 3
        assert s["cooldown_s"] == 5.0
        assert s["grow_step"] == 2
        assert s["shrink_factor"] == 2

    def test_custom_params(self) -> None:
        c = LoadAdaptiveController(
            low_ratio=0.1,
            high_ratio=0.8,
            ewma_alpha=0.5,
            hysteresis_samples=5,
            cooldown_s=10.0,
            grow_step=4,
            shrink_factor=3,
        )
        s = c.state()
        assert s["low_ratio"] == 0.1
        assert s["high_ratio"] == 0.8
        assert s["ewma_alpha"] == 0.5
        assert s["hysteresis_samples"] == 5
        assert s["cooldown_s"] == 10.0
        assert s["grow_step"] == 4
        assert s["shrink_factor"] == 3

    def test_invalid_ratios_raises(self) -> None:
        with pytest.raises(ValueError):
            LoadAdaptiveController(low_ratio=0.6, high_ratio=0.2)

    def test_invalid_alpha_raises(self) -> None:
        with pytest.raises(ValueError):
            LoadAdaptiveController(ewma_alpha=0.0)
        with pytest.raises(ValueError):
            LoadAdaptiveController(ewma_alpha=-0.1)


# ── EWMA smoothing ────────────────────────────────────────────────────────


class TestEWMA:
    def test_first_sample_initialises_ewma(self) -> None:
        c = LoadAdaptiveController(ewma_alpha=0.3)
        d = c.decide(_metrics(queue_ratio=0.5), now=100.0)
        assert d.ewma_depth == 0.5  # first sample initialises

    def test_ewma_smoothing(self) -> None:
        c = LoadAdaptiveController(ewma_alpha=0.3)
        # Sample 1: 0.5 → ewma = 0.5 (init)
        c.decide(_metrics(queue_ratio=0.5), now=100.0)
        # Sample 2: 0.9 → ewma = 0.3*0.9 + 0.7*0.5 = 0.27 + 0.35 = 0.62
        d = c.decide(_metrics(queue_ratio=0.9), now=101.0)
        assert d.ewma_depth == pytest.approx(0.62, rel=1e-3)


# ── Target band / HOLD ────────────────────────────────────────────────────


class TestHold:
    def test_within_band_returns_hold(self) -> None:
        c = LoadAdaptiveController()
        d = c.decide(_metrics(queue_ratio=0.4, worker_count=8), now=100.0)
        assert d.action == Action.HOLD
        assert d.reason == "within target band"

    def test_at_low_boundary_returns_hold(self) -> None:
        c = LoadAdaptiveController()
        d = c.decide(_metrics(queue_ratio=0.2, worker_count=8), now=100.0)
        assert d.action == Action.HOLD

    def test_at_high_boundary_returns_hold(self) -> None:
        c = LoadAdaptiveController()
        d = c.decide(_metrics(queue_ratio=0.6, worker_count=8), now=100.0)
        assert d.action == Action.HOLD


# ── Hysteresis ────────────────────────────────────────────────────────────


class TestHysteresis:
    def test_single_spike_ignored(self) -> None:
        c = LoadAdaptiveController(hysteresis_samples=3)
        # 1st out-of-bound sample → HOLD (hysteresis 1/3)
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=100.0)
        assert d.action == Action.HOLD
        assert "hysteresis" in d.reason

    def test_two_spikes_ignored(self) -> None:
        c = LoadAdaptiveController(hysteresis_samples=3)
        c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=100.0)
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=101.0)
        assert d.action == Action.HOLD

    def test_three_spikes_triggers_grow(self) -> None:
        c = LoadAdaptiveController(hysteresis_samples=3, grow_step=2)
        c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=100.0)
        c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=101.0)
        d3 = c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=102.0)
        assert d3.action == Action.GROW
        assert d3.target_workers == 10  # 8 + 2

    def test_returns_to_band_resets_counter(self) -> None:
        c = LoadAdaptiveController(hysteresis_samples=3)
        c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=100.0)
        c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=101.0)
        # Back in band resets counter
        c.decide(_metrics(queue_ratio=0.4, worker_count=8), now=102.0)
        # Now 3 more out-of-band needed
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=103.0)
        assert d.action == Action.HOLD  # counter reset, only 1/3


# ── Grow decision ─────────────────────────────────────────────────────────


class TestGrow:
    def test_grow_adds_step(self) -> None:
        c = LoadAdaptiveController(grow_step=2, hysteresis_samples=1, cooldown_s=0.0)
        # First call initialises EWMA + makes decision (hysteresis=1)
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=100.0)
        assert d.action == Action.GROW
        assert d.target_workers == 10

    def test_grow_respects_max(self) -> None:
        c = LoadAdaptiveController(grow_step=2, hysteresis_samples=1, cooldown_s=0.0)
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=32, worker_max=32), now=100.0)
        assert d.target_workers == 32


# ── Shrink decision ───────────────────────────────────────────────────────


class TestShrink:
    def test_shrink_divides_by_factor(self) -> None:
        c = LoadAdaptiveController(shrink_factor=2, hysteresis_samples=1, cooldown_s=0.0)
        d = c.decide(_metrics(queue_ratio=0.0, worker_count=16, worker_min=4), now=100.0)
        assert d.action == Action.SHRINK
        assert d.target_workers == 8  # 16 // 2

    def test_shrink_respects_min(self) -> None:
        c = LoadAdaptiveController(shrink_factor=2, hysteresis_samples=1, cooldown_s=0.0)
        # 5 // 2 = 2, but min is 4
        d = c.decide(_metrics(queue_ratio=0.0, worker_count=5, worker_min=4), now=100.0)
        assert d.target_workers == 4


# ── Cooldown ──────────────────────────────────────────────────────────────


class TestCooldown:
    def test_decision_triggers_cooldown(self) -> None:
        c = LoadAdaptiveController(cooldown_s=10.0, hysteresis_samples=1)
        # First call initialises EWMA + makes decision (hysteresis=1)
        c.decide(_metrics(queue_ratio=0.9, worker_count=8, worker_max=32), now=100.0)
        # Now inside cooldown
        d2 = c.decide(_metrics(queue_ratio=0.9, worker_count=8, worker_max=32), now=105.0)
        assert d2.action == Action.HOLD
        assert d2.in_cooldown is True

    def test_cooldown_expires(self) -> None:
        c = LoadAdaptiveController(cooldown_s=10.0, hysteresis_samples=1)
        c.decide(_metrics(queue_ratio=0.9, worker_count=8, worker_max=32), now=100.0)
        # Wait for cooldown to expire
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8, worker_max=32), now=112.0)
        assert d.action == Action.GROW


# ── Slow-task detection ───────────────────────────────────────────────────


class TestSlowTask:
    def test_slow_task_triggers_grow_fast(self) -> None:
        c = LoadAdaptiveController(
            hysteresis_samples=1,
            task_timeout=30.0,
            slow_task_ratio=0.5,
            cooldown_s=0.0,
        )
        # task_elapsed > 15s (50% of 30s) AND queue_ratio > HIGH
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8, task_elapsed=20.0), now=100.0)
        assert d.action == Action.GROW_FAST
        # grow_step * 2 = 4, so 8 + 4 = 12
        assert d.target_workers == 12

    def test_fast_task_does_not_trigger_grow_fast(self) -> None:
        c = LoadAdaptiveController(
            hysteresis_samples=1,
            task_timeout=30.0,
            slow_task_ratio=0.5,
            cooldown_s=0.0,
        )
        # task_elapsed < 15s → regular GROW
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8, task_elapsed=5.0), now=100.0)
        assert d.action == Action.GROW
        assert d.target_workers == 10  # 8 + 2


# ── Reset ─────────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_state(self) -> None:
        c = LoadAdaptiveController(hysteresis_samples=1, cooldown_s=0.0)
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=8), now=100.0)
        assert d.action == Action.GROW
        assert c.state()["decisions_total"] >= 1
        c.reset()
        s = c.state()
        assert s["decisions_total"] == 0
        assert s["ewma"] == 0.0
        assert s["out_of_bounds_count"] == 0


# ── Observability ─────────────────────────────────────────────────────────


class TestObservability:
    def test_state_returns_all_keys(self) -> None:
        c = LoadAdaptiveController()
        s = c.state()
        assert "ewma" in s
        assert "decisions_total" in s
        assert "low_ratio" in s
        assert "high_ratio" in s
        assert "cooldown_s" in s
        assert "grow_step" in s
        assert "shrink_factor" in s


# ── Integration: full control cycle ───────────────────────────────────────


class TestControlCycle:
    def test_overload_then_idle_cycle(self) -> None:
        """Simulate: overload → grow → settle → idle → shrink."""
        c = LoadAdaptiveController(
            hysteresis_samples=1,
            cooldown_s=0.0,
            grow_step=2,
            shrink_factor=2,
        )
        now = 100.0

        # Phase 1: overload (queue_ratio=0.9) → grow
        d = c.decide(_metrics(queue_ratio=0.9, worker_count=4, worker_min=4, worker_max=32), now=now)
        assert d.action == Action.GROW
        assert d.target_workers == 6
        now += 1.0

        # Phase 2: idle (queue_ratio=0.0) → EWMA decays below 0.2 after ~5 samples
        # EWMA: 0.63 → 0.441 → 0.309 → 0.216 → 0.151
        for _ in range(5):
            d = c.decide(_metrics(queue_ratio=0.0, worker_count=6, worker_min=4, worker_max=32), now=now)
            now += 1.0
        # 6th sample: EWMA ~0.106 < 0.2 → SHRINK
        d = c.decide(_metrics(queue_ratio=0.0, worker_count=6, worker_min=4, worker_max=32), now=now)
        assert d.action == Action.SHRINK
        assert d.target_workers == 4  # 6 // 2 = 3, clamped to min=4
