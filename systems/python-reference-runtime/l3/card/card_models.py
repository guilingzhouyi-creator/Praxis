"""CardUnified — shared card data models (enums + component records).

Extracted from ``card_unified.py``: the lifecycle / phase-mode enums and
the six component records (summary / task / phase / timestamps / execution
/ modification) used by the CardUnified dataclass and its serializers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_80, LOG_TRUNC_200, LOG_TRUNC_500


class CardLifecycle(Enum):
    """CardLifecycle — enum of card lifecycle variants."""

    DRAFT = "draft"
    QUEUED = "queued"
    HOLD = "hold"  # held for approval / awaiting human decision
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PhaseMode(Enum):
    """PhaseMode — enum of phase mode variants."""

    SINGLE = "single"  # one agent handles all tasks
    MULTI = "multi"  # tasks distributed to multiple agents


@dataclass
class CardSummary:
    """CardSummary — card summary record (title, description, columns)."""

    title: str = ""
    description: str = ""
    columns: dict[str, str] = field(default_factory=dict)
    # columns = {"Domain": "app/auth", "Risk": "low", "Files": "3", ...}

    def set_column(self, key: str, value: str) -> None:
        """Set a summary column value by key."""
        self.columns[key] = value

    def to_dict(self) -> dict:
        """Serialize the summary to a dict with truncated description."""
        return {
            "title": self.title,
            "description": self.description[:LOG_TRUNC_500],
            "columns": dict(self.columns),
        }


@dataclass
class CardTask:
    """CardTask — card task record (action, target, params, agent, state)."""

    action: str = ""
    target: str = ""
    params: dict = field(default_factory=dict)
    agent: str = ""  # resolved agent_id; "" = auto-assign
    state: str = "pending"  # pending | running | done | failed | skipped
    result: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        """Serialize the task to a dict with truncated error."""
        return {
            "action": self.action,
            "target": self.target,
            "agent": self.agent,
            "state": self.state,
            "error": self.error[:LOG_TRUNC_80] if self.error else "",
        }


@dataclass
class CardPhase:
    """CardPhase — card phase record (name, mode, agents, tasks, review_prompt)."""

    name: str = ""
    mode: PhaseMode = PhaseMode.SINGLE
    agents: list[str] = field(default_factory=list)  # assigned agents; empty=auto
    tasks: list[CardTask] = field(default_factory=list)
    review_prompt: str = ""  # configurable, from YAML or API
    strategy: str = ""  # named model_spec strategy pack for this phase (opusplan-style)
    state: str = "pending"  # pending | running | done | failed

    def to_dict(self) -> dict:
        """Serialize the phase to a dict with its tasks."""
        return {
            "name": self.name,
            "mode": self.mode.value,
            "agents": list(self.agents),
            "state": self.state,
            "strategy": self.strategy,
            "tasks": [t.to_dict() for t in self.tasks],
            "has_review_prompt": bool(self.review_prompt),
        }


@dataclass
class CardTimestamps:
    """CardTimestamps — card timestamps record (created_at, submitted_at, dispatched_at, completed_at)."""

    created_at: float = field(default_factory=time.time)  # L3A creates card
    submitted_at: float = 0.0  # registered in queue
    dispatched_at: float = 0.0  # sent to Cell
    completed_at: float = 0.0  # all phases done

    def to_dict(self) -> dict:
        """Serialize the timestamps to a dict."""
        return {
            "created_at": self.created_at,
            "submitted_at": self.submitted_at,
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
        }


@dataclass
class CardExecution:
    """One executor's wall-time contribution to a card.

    Two granularities:
      cell-level:  executor == "<cell>" (whole Cell.execute_card elapsed)
      agent-level: executor == agent_id (one Peer Agent step, from ExecutionPlan)
    """

    executor: str = ""
    cell_id: str = ""
    phase: str = ""  # phase/step label
    started_at: float = 0.0
    finished_at: float = 0.0
    elapsed: float = 0.0
    success: bool = False

    def to_dict(self) -> dict:
        """Serialize the execution record to a dict with rounded elapsed."""
        return {
            "executor": self.executor,
            "cell_id": self.cell_id,
            "phase": self.phase,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": round(self.elapsed, 3),
            "success": self.success,
        }


@dataclass
class CardModification:
    """CardModification — card modification record (version, timestamp, field, old_value, new_value)."""

    version: int = 0
    timestamp: float = 0.0
    field: str = ""  # "summary.title", "phases[0].tasks", "priority", etc.
    old_value: Any = None
    new_value: Any = None

    def to_dict(self) -> dict:
        """Serialize the modification to a dict with truncated value previews."""
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "field": self.field,
            "old_preview": str(self.old_value)[:LOG_TRUNC_200] if self.old_value else "",
            "new_preview": str(self.new_value)[:LOG_TRUNC_200] if self.new_value else "",
        }
