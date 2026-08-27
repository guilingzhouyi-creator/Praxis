"""HTN planner — shared data models.

Extracted from ``htn_planner.py``: the TaskType / TaskStatus enums, the
Task dataclass, the DecompositionMethod record and the identity matcher
used by the planner and by L3A's decision layer.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class TaskType(Enum):
    """TaskType — enum of PRIMITIVE, COMPOUND."""

    PRIMITIVE = auto()  # Atomic action, can be executed directly
    COMPOUND = auto()  # Has sub-tasks, needs decomposition


class TaskStatus(Enum):
    """TaskStatus — enum of PENDING, RUNNING, DONE, FAILED...."""

    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class Task:
    """A single task in the HTN hierarchy."""

    id: str
    name: str
    task_type: TaskType = TaskType.COMPOUND
    description: str = ""
    domain: str = ""
    tool: str = ""  # For PRIMITIVE tasks: the tool to execute
    params: dict = field(default_factory=dict)
    sub_tasks: list[Task] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    priority: int = 5
    agent_id: str = ""
    identity: str = ""  # generic identity field (build|test|review) matched by HTN-C
    created_at: float = field(default_factory=time.time)

    def is_primitive(self) -> bool:
        """Return True if this task is a primitive action."""
        return self.task_type == TaskType.PRIMITIVE


def match_identity(intent: str, domain: str = "") -> str:
    """Match an intent/domain to one of the three generic identity fields.

    The three standard identities (build / test / review) are data, not
    hardcoded roles: keyword patterns are declared in config/discovery/
    identity_roles.yaml (loaded via discovery) with params fallbacks.
    Returns the identity field name, or "" when nothing matches.

    Args:
        intent: Task intent / description text (lowercased for matching).
        domain: Optional card domain hint (e.g. "test" routes to test).

    Returns:
        One of IDENTITY_FIELDS values, or "".
    """
    from l1.kernel.params.agent import IDENTITY_FIELDS
    from l3.agent.prompts import get_prompt

    text = f"{intent} {domain}".lower()
    # Intent keywords per identity — declared as prompt-registry data so
    # deployment can override without code changes (praxis.yaml prompts:
    # section via load_prompt_overrides).
    for identity in IDENTITY_FIELDS:
        patterns = get_prompt(f"identity.match.{identity}", "")
        if not patterns:
            continue
        for pattern in patterns.split("|"):
            if pattern and pattern in text:
                return identity
    return ""


@dataclass
class DecompositionMethod:
    """A method for decomposing a compound task into sub-tasks."""

    name: str
    domain: str
    patterns: list[str]
    decompose_fn: Callable
