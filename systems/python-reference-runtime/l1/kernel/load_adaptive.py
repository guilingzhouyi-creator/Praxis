"""Load-adaptive thread pool controller.

Pure algorithm (no I/O, no OS dependencies) — the control law is a
self-contained numerical function suitable for FFI porting to Rust.

Architecture
------------
    Load signals (periodic sampling)     LoadAdaptiveController (pure)
    ──────────────────────                ──────────────────────────────
      queue_ratio     ──► EWMA smoothing ──► target interval [LOW, HIGH]
      completion_rate ──► hysteresis       ├─ below LOW  → shrink (×1/2)
      active_ratio    ──► cooldown timer   ├─ above HIGH → grow (+2)
      task_elapsed    ──► output target    └─ in band    → hold
                                           │
                                           ▼
                               ThreadPoolWorker.grow()/shrink()

Usage
-----
    controller = LoadAdaptiveController()
    action = controller.decide(metrics)   # returns Action enum
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from l1.kernel.params.api import (
    LOAD_ADAPTIVE_COOLDOWN_S,
    LOAD_ADAPTIVE_EWMA_ALPHA,
    LOAD_ADAPTIVE_GROW_STEP,
    LOAD_ADAPTIVE_HIGH_RATIO,
    LOAD_ADAPTIVE_HYSTERESIS_SAMPLES,
    LOAD_ADAPTIVE_LOW_RATIO,
    LOAD_ADAPTIVE_SHRINK_FACTOR,
    LOAD_ADAPTIVE_SLOW_TASK_RATIO,
    WORKER_POOL_TASK_TIMEOUT,
)

logger = __import__("logging").getLogger(__name__)


class Action(Enum):
    """Controller decision emitted by decide()."""

    HOLD = auto()
    GROW = auto()
    SHRINK = auto()
    GROW_FAST = auto()


@dataclass
class ControllerMetrics:
    """Snapshot of thread-pool signals fed into decide()."""

    queue_ratio: float = 0.0
    completion_rate: float = 0.0
    active_ratio: float = 0.0
    task_elapsed: float = 0.0
    worker_count: int = 0
    worker_min: int = 1
    worker_max: int = 32


@dataclass
class ControllerState:
    """Persistent state of the controller between sampling cycles."""

    ewma: float = 0.0
    _out_of_bounds_count: int = 0
    _last_decision_at: float = 0.0
    decisions_total: int = 0


@dataclass
class Decision:
    """Result of a single decide() call."""

    action: Action = Action.HOLD
    target_workers: int = 0
    ewma_depth: float = 0.0
    in_cooldown: bool = False
    reason: str = ""


class LoadAdaptiveController:
    """Load-adaptive controller for thread-pool sizing.

    This is a **pure algorithm** — no file I/O, no network, no OS calls.
    It consumes ControllerMetrics snapshots and returns Decision.
    The caller is responsible for periodic sampling and applying the action.
    """

    def __init__(
        self,
        low_ratio: float = LOAD_ADAPTIVE_LOW_RATIO,
        high_ratio: float = LOAD_ADAPTIVE_HIGH_RATIO,
        ewma_alpha: float = LOAD_ADAPTIVE_EWMA_ALPHA,
        hysteresis_samples: int = LOAD_ADAPTIVE_HYSTERESIS_SAMPLES,
        cooldown_s: float = LOAD_ADAPTIVE_COOLDOWN_S,
        grow_step: int = LOAD_ADAPTIVE_GROW_STEP,
        shrink_factor: int = LOAD_ADAPTIVE_SHRINK_FACTOR,
        slow_task_ratio: float = LOAD_ADAPTIVE_SLOW_TASK_RATIO,
        task_timeout: float = WORKER_POOL_TASK_TIMEOUT,
    ) -> None:
        if not (0.0 <= low_ratio < high_ratio <= 1.0):
            raise ValueError(f"need 0 <= low_ratio ({low_ratio}) < high_ratio ({high_ratio}) <= 1.0")
        if not (0.0 < ewma_alpha <= 1.0):
            raise ValueError(f"ewma_alpha must be in (0, 1], got {ewma_alpha}")
        self._low_ratio = low_ratio
        self._high_ratio = high_ratio
        self._ewma_alpha = ewma_alpha
        self._hysteresis_samples = hysteresis_samples
        self._cooldown_s = cooldown_s
        self._grow_step = grow_step
        self._shrink_factor = shrink_factor
        self._slow_task_ms = task_timeout * slow_task_ratio
        self._state = ControllerState()

    def decide(self, metrics: ControllerMetrics, now: float | None = None) -> Decision:
        """Run one control-law cycle and return a decision."""
        if now is None:
            now = time.monotonic()

        ewma = self._update_ewma(metrics.queue_ratio)

        in_cooldown = (now - self._state._last_decision_at) < self._cooldown_s
        if in_cooldown:
            return Decision(
                action=Action.HOLD,
                target_workers=metrics.worker_count,
                ewma_depth=ewma,
                in_cooldown=True,
                reason="in cooldown",
            )

        in_band = self._low_ratio <= ewma <= self._high_ratio
        if in_band:
            self._state._out_of_bounds_count = 0
            return Decision(
                action=Action.HOLD,
                target_workers=metrics.worker_count,
                ewma_depth=ewma,
                in_cooldown=False,
                reason="within target band",
            )

        self._state._out_of_bounds_count += 1
        if self._state._out_of_bounds_count < self._hysteresis_samples:
            return Decision(
                action=Action.HOLD,
                target_workers=metrics.worker_count,
                ewma_depth=ewma,
                in_cooldown=False,
                reason=f"hysteresis ({self._state._out_of_bounds_count}/{self._hysteresis_samples})",
            )

        target = metrics.worker_count
        action: Action = Action.HOLD
        reason = ""

        if ewma > self._high_ratio:
            is_slow = metrics.task_elapsed > self._slow_task_ms and metrics.queue_ratio > self._high_ratio
            if is_slow:
                step = self._grow_step * 2
                action = Action.GROW_FAST
                reason = f"slow tasks detected, grow fast +{step}"
            else:
                step = self._grow_step
                action = Action.GROW
                reason = f"queue ratio {ewma:.3f} > {self._high_ratio}, grow +{step}"
            target = min(metrics.worker_count + step, metrics.worker_max)

        elif ewma < self._low_ratio:
            shrunk = max(metrics.worker_count // self._shrink_factor, metrics.worker_min)
            target = shrunk
            action = Action.SHRINK
            reason = f"queue ratio {ewma:.3f} < {self._low_ratio}, shrink to {target}"

        self._state._last_decision_at = now
        self._state._out_of_bounds_count = 0
        self._state.decisions_total += 1

        return Decision(
            action=action,
            target_workers=target,
            ewma_depth=ewma,
            in_cooldown=False,
            reason=reason,
        )

    def reset(self) -> None:
        """Reset the controller to its initial state."""
        self._state = ControllerState()

    def state(self) -> dict[str, Any]:
        """Return serialisable controller state for observability."""
        return {
            "ewma": round(self._state.ewma, 4),
            "out_of_bounds_count": self._state._out_of_bounds_count,
            "last_decision_elapsed": (
                round(time.monotonic() - self._state._last_decision_at, 2) if self._state._last_decision_at else 0.0
            ),
            "decisions_total": self._state.decisions_total,
            "low_ratio": self._low_ratio,
            "high_ratio": self._high_ratio,
            "ewma_alpha": self._ewma_alpha,
            "hysteresis_samples": self._hysteresis_samples,
            "cooldown_s": self._cooldown_s,
            "grow_step": self._grow_step,
            "shrink_factor": self._shrink_factor,
        }

    def _update_ewma(self, queue_ratio: float) -> float:
        """Update and return the smoothed queue-ratio signal."""
        if self._state.decisions_total == 0 and self._state.ewma == 0.0:
            self._state.ewma = queue_ratio
        else:
            self._state.ewma = self._ewma_alpha * queue_ratio + (1.0 - self._ewma_alpha) * self._state.ewma
        return self._state.ewma
