"""CardUnified — single unified card model for the entire Agent OS.

Replaces the fragmented card types (Card, CardRecord, TaskCard, etc.)
with one universal data model that covers all card natures.

Module layout (split for readability):
  card_models.py      — enums (CardLifecycle / PhaseMode) + component records
                        (CardSummary / CardTask / CardPhase / CardTimestamps /
                        CardExecution / CardModification)
  card_type_registry.py — card type registry (register/list/load + builtins)
  card_unified.py     — CardUnified dataclass (this facade, re-exports both)

Card lifecycle:
  DRAFT → QUEUED → DISPATCHED → RUNNING → COMPLETED | FAILED | CANCELLED
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import HASH_TRUNC_SHORT, LOG_TRUNC_80, LOG_TRUNC_500

from .card_models import (  # noqa: F401 — re-export
    CardExecution,
    CardLifecycle,
    CardModification,
    CardPhase,
    CardSummary,
    CardTask,
    CardTimestamps,
    PhaseMode,
)
from .card_type_registry import (  # noqa: F401 — re-export
    get_card_type,
    list_card_types,
    load_card_types,
    register_card_type,
)

logger = logging.getLogger(__name__)


@dataclass
class CardUnified:
    """CardUnified — card unified record (id, nature, priority, state, summary)."""

    id: str = field(default_factory=lambda: f"card-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}")
    nature: str = "execution"  # card type name from registry
    priority: int = 5  # 1-10, 1=highest
    state: CardLifecycle = CardLifecycle.DRAFT
    summary: CardSummary = field(default_factory=CardSummary)
    phases: list[CardPhase] = field(default_factory=list)
    error: str = ""

    # ── Approval trail (stamped by card_gate; read by L4 API) ──
    approval_status: str = ""
    approval_size: str = ""
    approval_at: float = 0.0
    approval_by: str = ""
    lifecycle: str = ""

    # ── Card execution scope (visible to Agent, verified by GateChain) ──
    scope: str = ""
    """Overall execution scope for this card (e.g. 'project/auth'). Agent sees this."""

    # ── Hidden system fields ──
    timestamps: CardTimestamps = field(default_factory=CardTimestamps)
    modifications: list[CardModification] = field(default_factory=list)
    executions: list[CardExecution] = field(default_factory=list)
    _gate_scope: str = ""
    """GateChain enforcement scope — NOT exposed to LLM context. Passed to GateChain."""
    _completion_summary: str = ""
    _changes: list[dict] = field(default_factory=list)  # actual file/system changes
    _depends_on: list[str] = field(default_factory=list)  # dependency card IDs

    # ── Modification tracking ──

    def _track_mod(self, field: str, old: Any, new: Any) -> None:
        self.modifications.append(
            CardModification(
                version=len(self.modifications) + 1,
                timestamp=time.time(),
                field=field,
                old_value=old,
                new_value=new,
            )
        )

    def set_nature(self, nature: str) -> None:
        """Change the card nature and record the modification."""
        old = self.nature
        self.nature = nature
        self._track_mod("nature", old, nature)

    def set_priority(self, priority: int) -> None:
        """Set the priority clamped to 1-10 and record the modification."""
        old = self.priority
        self.priority = max(1, min(10, priority))
        self._track_mod("priority", old, self.priority)

    def set_summary_column(self, key: str, value: str) -> None:
        """Set a summary column value and record the modification."""
        old = self.summary.columns.get(key, "")
        self.summary.set_column(key, value)
        self._track_mod(f"summary.columns.{key}", old, value)

    def update_title(self, title: str) -> None:
        """Update the summary title and record the modification."""
        old = self.summary.title
        self.summary.title = title
        self._track_mod("summary.title", old, title)

    # ── Lifecycle ──

    def submit(self) -> None:
        """Mark as queued, set submission timestamp."""
        self.state = CardLifecycle.QUEUED
        self.timestamps.submitted_at = time.time()

    def dispatch(self) -> None:
        """Mark as dispatched to Cell."""
        self.state = CardLifecycle.DISPATCHED
        self.timestamps.dispatched_at = time.time()

    def complete(self, summary: str = "", changes: list[dict] | None = None) -> None:
        """Mark the card as completed, storing the summary and changes."""
        self.state = CardLifecycle.COMPLETED
        self.timestamps.completed_at = time.time()
        self._completion_summary = summary
        if changes:
            self._changes = changes

    def fail(self, error: str) -> None:
        """Mark the card as failed and store the error message."""
        self.state = CardLifecycle.FAILED
        self.timestamps.completed_at = time.time()
        self.error = error

    # ── Old-model bridge ──

    def to_old_card(self):
        """Convert CardUnified → old Card (card.py) for backward compat.

        Used during the Phase 1→2 migration so that existing
        ExecutionPlan / cell.execute_card() can consume CardUnified
        without being rewritten all at once.
        """
        from .models import Card as OldCard
        from .models import CardMode as OldCardMode
        from .models import Phase as OldPhase
        from .models import PhaseMode as OldPhaseMode
        from .models import Step as OldStep

        # Map nature → CardMode
        mode_map = {
            "execution": OldCardMode.EXECUTE,
            "issue": OldCardMode.ISSUE,
            "parallel_all": OldCardMode.PARALLEL_ALL,
        }
        old_mode = mode_map.get(self.nature, OldCardMode.EXECUTE)

        # Map PhaseMode
        phase_mode_map = {
            PhaseMode.SINGLE: OldPhaseMode.SEQUENTIAL,
            PhaseMode.MULTI: OldPhaseMode.PARALLEL,
        }

        old_phases = []
        for phase in self.phases:
            old_steps = []
            for task in phase.tasks:
                old_steps.append(
                    OldStep(
                        action=task.action,
                        target=task.target,
                        params=dict(task.params),
                        agent=task.agent,
                    )
                )
            old_mode_phase = phase_mode_map.get(phase.mode, OldPhaseMode.SEQUENTIAL)
            old_phases.append(
                OldPhase(
                    name=phase.name,
                    steps=old_steps,
                    mode=old_mode_phase,
                )
            )

        domain = self.summary.columns.get("domain", self.nature)
        cell_id = self.summary.columns.get("cell_id", "")
        return OldCard(
            id=self.id,
            intent=self.summary.title,
            domain=domain,
            mode=old_mode,
            phases=old_phases,
            priority=self.priority,
            sender="l3",
            cell_id=cell_id,
        )

    # ── Phase management ──

    def add_phase(
        self,
        name: str,
        mode: PhaseMode = PhaseMode.SINGLE,
        agents: list[str] | None = None,
        review_prompt: str = "",
        strategy: str = "",
    ) -> CardPhase:
        """Append a new phase to the card and return it."""
        phase = CardPhase(
            name=name,
            mode=mode,
            agents=agents or [],
            review_prompt=review_prompt,
            strategy=strategy,
        )
        self.phases.append(phase)
        self._track_mod("phases.add", None, name)
        return phase

    def add_task(
        self, phase_name: str, action: str, target: str = "", params: dict | None = None, agent: str = ""
    ) -> CardTask | None:
        """Append a task to the named phase, or return None if the phase is absent."""
        for phase in self.phases:
            if phase.name == phase_name:
                task = CardTask(action=action, target=target, params=params or {}, agent=agent)
                phase.tasks.append(task)
                return task
        return None

    def resolve_agents(self, agent_map: dict[str, str], default_agent: str = "") -> None:
        """Resolve role → agent_id for all phases and tasks.

        Single mode: all tasks go to the first available agent.
        Multi mode: tasks are distributed by their agent field.
        If a phase has no agents specified, auto-assign by round-robin
        or first-available from agent_map.
        """
        used_agents = list(agent_map.values()) if agent_map else []
        for phase in self.phases:
            if phase.mode == PhaseMode.SINGLE:
                if phase.agents:
                    agent = phase.agents[0]
                elif used_agents:
                    agent = used_agents[0]
                elif default_agent:
                    agent = default_agent
                else:
                    continue  # no agent available → skip this phase
                phase.agents = [agent] if agent else phase.agents
                for task in phase.tasks:
                    task.agent = agent
            else:  # MULTI
                if not phase.agents:
                    phase.agents = list(used_agents)
                for i, task in enumerate(phase.tasks):
                    if not task.agent and phase.agents:
                        task.agent = phase.agents[i % len(phase.agents)]

    # ── Review ──

    def needs_review(self) -> bool:
        """Return whether the card's type requires review."""
        td = get_card_type(self.nature)
        return td.get("has_review", False) if td else False

    def review_phases(self) -> list[CardPhase]:
        """Return all phases that carry a review prompt."""
        return [p for p in self.phases if p.review_prompt]

    # ── Serialization ──

    def to_dict(self, include_hidden: bool = False) -> dict:
        """Serialize the card to a dict, optionally including hidden fields."""
        base = {
            "id": self.id,
            "nature": self.nature,
            "priority": self.priority,
            "state": self.state.value,
            "summary": self.summary.to_dict(),
            "phases": [p.to_dict() for p in self.phases],
            "error": self.error[:LOG_TRUNC_80] if self.error else "",
        }
        if include_hidden:
            base["timestamps"] = self.timestamps.to_dict()
            base["modifications"] = [m.to_dict() for m in self.modifications]
            base["executions"] = [e.to_dict() for e in self.executions]
            base["_completion_summary"] = self._completion_summary[:LOG_TRUNC_500]
            base["_changes"] = list(self._changes)[-20:]
        return base

    def to_persist(self) -> dict:
        """Full serialization for persistence (includes hidden fields)."""
        return {
            "card_version": 1,
            "id": self.id,
            "nature": self.nature,
            "priority": self.priority,
            "state": self.state.value,
            "summary": {
                "title": self.summary.title,
                "description": self.summary.description,
                "columns": dict(self.summary.columns),
            },
            "phases": [
                {
                    "name": p.name,
                    "mode": p.mode.value,
                    "agents": list(p.agents),
                    "state": p.state,
                    "review_prompt": p.review_prompt,
                    "strategy": p.strategy,
                    "tasks": [
                        {
                            "action": t.action,
                            "target": t.target,
                            "params": dict(t.params),
                            "agent": t.agent,
                            "state": t.state,
                            "error": t.error,
                        }
                        for t in p.tasks
                    ],
                }
                for p in self.phases
            ],
            "error": self.error,
            "timestamps": {
                "created_at": self.timestamps.created_at,
                "submitted_at": self.timestamps.submitted_at,
                "dispatched_at": self.timestamps.dispatched_at,
                "completed_at": self.timestamps.completed_at,
            },
            "depends_on": list(self._depends_on),
            "modifications": [
                {
                    "version": m.version,
                    "timestamp": m.timestamp,
                    "field": m.field,
                }
                for m in self.modifications
            ],
            "executions": [
                {
                    "executor": e.executor,
                    "cell_id": e.cell_id,
                    "phase": e.phase,
                    "started_at": e.started_at,
                    "finished_at": e.finished_at,
                    "elapsed": e.elapsed,
                    "success": e.success,
                }
                for e in self.executions
            ],
            "_completion_summary": self._completion_summary,
            "_changes": list(self._changes)[-50:],
        }

    @staticmethod
    def from_persist(data: dict) -> CardUnified:
        """Rebuild a CardUnified from a persisted dict."""
        card = CardUnified(
            id=data.get("id", ""),
            nature=data.get("nature", "execution"),
            priority=data.get("priority", 5),
            state=CardLifecycle(data.get("state", "draft")),
            error=data.get("error", ""),
        )
        s = data.get("summary", {})
        card.summary = CardSummary(
            title=s.get("title", ""),
            description=s.get("description", ""),
            columns=dict(s.get("columns", {})),
        )
        for pd in data.get("phases", []):
            phase = CardPhase(
                name=pd.get("name", ""),
                mode=PhaseMode(pd.get("mode", "single")),
                agents=list(pd.get("agents", [])),
                state=pd.get("state", "pending"),
                review_prompt=pd.get("review_prompt", ""),
                strategy=pd.get("strategy", ""),
            )
            for td in pd.get("tasks", []):
                phase.tasks.append(
                    CardTask(
                        action=td.get("action", ""),
                        target=td.get("target", ""),
                        params=dict(td.get("params", {})),
                        agent=td.get("agent", ""),
                        state=td.get("state", "pending"),
                        error=td.get("error", ""),
                    )
                )
            card.phases.append(phase)
        ts = data.get("timestamps", {})
        card.timestamps = CardTimestamps(
            created_at=ts.get("created_at", 0.0),
            submitted_at=ts.get("submitted_at", 0.0),
            dispatched_at=ts.get("dispatched_at", 0.0),
            completed_at=ts.get("completed_at", 0.0),
        )
        card._depends_on = list(data.get("depends_on", []))
        for md in data.get("modifications", []):
            card.modifications.append(
                CardModification(
                    version=md.get("version", 0),
                    timestamp=md.get("timestamp", 0.0),
                    field=md.get("field", ""),
                )
            )
        for ed in data.get("executions", []):
            card.executions.append(
                CardExecution(
                    executor=ed.get("executor", ""),
                    cell_id=ed.get("cell_id", ""),
                    phase=ed.get("phase", ""),
                    started_at=ed.get("started_at", 0.0),
                    finished_at=ed.get("finished_at", 0.0),
                    elapsed=ed.get("elapsed", 0.0),
                    success=ed.get("success", False),
                )
            )
        card._completion_summary = data.get("_completion_summary", "")
        card._changes = list(data.get("_changes", []))
        return card
