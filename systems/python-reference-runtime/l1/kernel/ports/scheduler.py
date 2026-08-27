"""Scheduler port — kernel-facing scheduling mechanism seam (W6.2).

The kernel never imports L3 scheduling internals; it talks scheduling
through this port. ``CentralScheduler`` (L3) implements it and is wired
at boot (``l3.boot.wiring.wire_defaults`` → port ``scheduler``).

Contract: submit/poll/preempt are the mechanism primitives; notify_event
carries process-lifecycle notifications (spawn/exit/cancel) from the
kernel syscall path into the scheduler's accounting.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KernelSchedulerPort(ABC):
    """Scheduling mechanism port — submit, poll, preempt, notify, stats."""

    @abstractmethod
    def submit(
        self,
        domain: str,
        command: str,
        args: dict | None = None,
        intent_tags: list[str] | None = None,
        preferred_agent: str | None = None,
        priority: int = 0,
    ) -> dict:
        """Enqueue a scheduling request; returns task_id on success."""

    @abstractmethod
    def poll(self) -> Any:
        """Dequeue the next ready task, or None when empty."""

    @abstractmethod
    def preempt(self, task_id: str, reason: str = "") -> dict:
        """Preempt/cancel a scheduled task by id."""

    @abstractmethod
    def notify_event(self, event: str, data: dict | None = None) -> None:
        """Receive a process-lifecycle notification (spawn/exit/cancel)."""

    @abstractmethod
    def stats(self) -> dict:
        """Aggregate scheduler dimension stats."""
