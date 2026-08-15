"""TodoTracker — persistent task state machine for AgentLoop.

Agent-harness-style: pending -> in_progress -> verifying -> verified | escalated.
State is persisted to JSON for cross-session recovery.
Close gate refuses if any task remains unverified and unwaived.
"""

from __future__ import annotations

import json
import logging
import os
import threading

from l1.kernel.params.system import LOG_TRUNC_40, LOG_TRUNC_60
from l1.kernel.paths import get_paths as _gp

logger = logging.getLogger(__name__)


class TodoTracker:
    """Persistent state machine for multi-step task execution.

    Task states:
      pending     - not started
      in_progress - agent is working on it
      verifying   - execution done, verification checks running
      verified    - all checks passed with evidence
      escalated   - max attempts exhausted, needs human review
      waived      - human explicitly waived verification
    """

    TASK_STATUSES = frozenset(
        {
            "pending",
            "in_progress",
            "verifying",
            "verified",
            "escalated",
            "waived",
            "add",
            "completed",
        }
    )

    _STATUS_ALIASES = {"add": "pending", "completed": "verified"}

    def __init__(self, state_path: str = ""):
        self._state_path = (
            state_path or os.environ.get("PRAXIS_TODO_STATE") or os.path.join(_gp().data_dir, "todo_state.json")
        )
        self._items: list[dict] = []
        self._read_cfg()
        self._iteration: int = 0
        self._status: str = "open"
        self._restore()

    def _read_cfg(self) -> None:
        try:
            from l3.config.settings_center import get_center

            center = get_center()
            self._max_iterations = center.get_int("loop.max_iterations", 50)
            self._max_attempts = center.get_int("loop.max_attempts", 3)
            self._continuation_nudge = center.get("loop.continuation_nudge", True)
        except Exception:
            self._max_iterations = 50
            self._max_attempts = 3
            self._continuation_nudge = True

    def _persist(self) -> None:
        try:
            data = {
                "status": self._status,
                "iteration": self._iteration,
                "max_attempts": self._max_attempts,
                "max_iterations": self._max_iterations,
                "tasks": list(self._items),
            }
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._state_path)
            # Register-backed snapshot: keep the L1 registry section in sync
            # so other executors / the status surface can read the TODO
            # table without touching the state file (layer-safe opaque copy).
            try:
                from l1.kernel.registry import get_registry

                get_registry().set_section(
                    "todo_table",
                    {
                        "status": self._status,
                        "iteration": self._iteration,
                        "tasks": list(self._items),
                    },
                )
            except Exception as e:
                logger.debug("todo register snapshot failed: %s", e)
        except Exception as e:
            logger.warning("todo persist: %s", e)

    def list_for_agent(self, agent_id: str) -> list[dict]:
        """Return tasks attributable to *agent_id* (empty if no agent scoping).

        Task items carry an optional ``agent_id`` field set by callers that
        track per-executor TODO tables; unscoped tasks are returned for the
        empty agent id only.
        """
        if not agent_id:
            return [dict(t) for t in self._items if not t.get("agent_id")]
        return [dict(t) for t in self._items if t.get("agent_id") == agent_id]

    def _restore(self) -> None:
        if not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            self._status = data.get("status", "open")
            self._iteration = data.get("iteration", 0)
            self._max_attempts = data.get("max_attempts", 3)
            self._max_iterations = data.get("max_iterations", 50)
            self._items = data.get("tasks", [])
        except Exception as e:
            logger.warning("todo restore: %s", e)

    def load(self, items: list[dict]) -> None:
        """Replace the task list with normalized copies of the given items."""
        self._items = [dict(item) for item in items]
        for t in self._items:
            t.setdefault("status", "pending")
            t.setdefault("attempts", 0)
            t.setdefault("evidence", [])
            t.setdefault("checks", [])
        self._persist()

    def update(self, content: str, status: str) -> str:
        """Transition a task's status; returns the new status or an error string."""
        if status not in self.TASK_STATUSES:
            return f"error: invalid status '{status}'"
        status = self._STATUS_ALIASES.get(status, status)
        task = self._find(content)
        if task is None:
            if status != "pending" and status != "add":
                return "error: new task must start as 'pending' or 'add'"
            self._items.append(
                {
                    "content": content,
                    "status": "pending" if status == "add" else status,
                    "attempts": 0,
                    "evidence": [],
                    "checks": [],
                }
            )
            self._persist()
            return "pending"
        return self._transition(task, content, status)

    def _transition(self, task: dict, content: str, status: str) -> str:
        """Apply a status transition to an existing task and return its new status."""
        old = task["status"]
        if old == "verified":
            return "verified" if status == "verified" else f"error: task '{content[:LOG_TRUNC_40]}' is already verified"
        if old == "escalated" and status != "waived":
            return f"error: task '{content[:LOG_TRUNC_40]}' is escalated"
        if old == "waived" and status not in ("verified", "waived"):
            return f"error: task '{content[:LOG_TRUNC_40]}' is waived"
        if old == "in_progress" and status == "verifying":
            task["status"] = "verifying"
            self._persist()
            return "verifying"
        if old == "pending" and status == "in_progress":
            task["status"] = "in_progress"
            self._persist()
            return "in_progress"
        task["status"] = status
        self._persist()
        return status

    def record_attempt(self, content: str, phase: str, exit_code: int, evidence: str = "") -> dict:
        """Record an execute/verify attempt; returns the next action to take."""
        task = self._find(content)
        if task is None:
            return {"action": "error", "detail": f"unknown task: {content[:LOG_TRUNC_40]}"}
        if self._status == "closed":
            return {"action": "error", "detail": "loop is closed"}
        if task["status"] in ("verified", "escalated", "waived"):
            return {"action": "error", "detail": f"task is {task['status']}"}
        self._iteration += 1
        if self._iteration >= self._max_iterations:
            self._status = "closed"
            self._persist()
            return {"action": "escalate", "detail": "global iteration cap reached"}
        entry = {"phase": phase, "exit_code": exit_code, "evidence": evidence, "attempt": task["attempts"] + 1}
        task["evidence"].append(entry)
        ok = exit_code == 0
        return self._record_phase(task, content, phase, ok, evidence)

    def _record_phase(self, task: dict, content: str, phase: str, ok: bool, evidence: str) -> dict:
        """Dispatch an attempt to its phase handler; unknown phases error."""
        if phase == "execute":
            return self._record_execute(task, content, ok)
        if phase == "verify":
            return self._record_verify(task, content, ok, evidence)
        return {"action": "error", "detail": f"unknown phase: {phase}"}

    def _record_execute(self, task: dict, content: str, ok: bool) -> dict:
        """Handle an execute-phase attempt and return the next action."""
        if ok:
            task["status"] = "verifying"
            self._persist()
            return {"action": "verify", "task": content[:LOG_TRUNC_40], "detail": "run verification checks"}
        return self._fail_task(task)

    def _record_verify(self, task: dict, content: str, ok: bool, evidence: str) -> dict:
        """Handle a verify-phase attempt and return the next action."""
        if task["status"] != "verifying":
            return {"action": "error", "detail": "task not in verify phase"}
        if ok:
            if not evidence:
                return {"action": "error", "detail": "passing verify requires --evidence"}
            task["status"] = "verified"
            self._persist()
            return {"action": "done", "task": content[:LOG_TRUNC_40], "detail": "verified", "evidence": evidence}
        return self._fail_task(task)

    def _fail_task(self, task: dict) -> dict:
        task["attempts"] += 1
        if task["attempts"] >= self._max_attempts:
            task["status"] = "escalated"
            self._persist()
            return {
                "action": "escalate",
                "task": task["content"][:LOG_TRUNC_40],
                "detail": f"exhausted {self._max_attempts} attempts",
            }
        task["status"] = "pending"
        self._persist()
        return {
            "action": "retry",
            "task": task["content"][:LOG_TRUNC_40],
            "detail": f"attempt {task['attempts']}/{self._max_attempts} failed",
        }

    def waive(self, content: str, reason: str = "") -> dict:
        """Mark a task as waived with an optional reason."""
        task = self._find(content)
        if task is None:
            return {"action": "error", "detail": f"unknown task: {content[:LOG_TRUNC_40]}"}
        task["status"] = "waived"
        task["evidence"].append({"phase": "waive", "reason": reason})
        self._persist()
        return {"action": "waived", "task": content[:LOG_TRUNC_40], "detail": reason}

    def can_close(self) -> tuple[bool, list[str]]:
        """Return whether every task is verified/waived, plus blockers."""
        blocked = [t["content"][:LOG_TRUNC_60] for t in self._items if t["status"] not in ("verified", "waived")]
        return len(blocked) == 0, blocked

    def has_open_items(self) -> bool:
        """Return whether any task is still pending/in-progress/verifying/escalated."""
        return any(t["status"] in ("pending", "in_progress", "verifying", "escalated") for t in self._items)

    def status_of(self, content: str) -> str:
        """Return a task's current status by content ("" when untracked)."""
        task = self._find(content)
        return task["status"] if task else ""

    def reminder(self) -> str | None:
        """Build a progress reminder/next-action prompt, or None when idle."""
        if self._status == "closed" or not self._items:
            return None
        in_progress = [t for t in self._items if t["status"] == "in_progress"]
        verifying = [t for t in self._items if t["status"] == "verifying"]
        pending = [t for t in self._items if t["status"] == "pending"]
        escalated = [t for t in self._items if t["status"] == "escalated"]
        lines = []
        if escalated:
            lines.append(f">> ESCALATED: {escalated[0]['content'][:LOG_TRUNC_60]} - needs human review")
        if verifying:
            lines.append(f">> Verifying: {verifying[0]['content'][:LOG_TRUNC_60]} - run checks")
        if in_progress:
            lines.append(f">> You are currently ON task '{in_progress[0]['content'][:LOG_TRUNC_60]}'")
        elif pending:
            lines.append(">> NOTHING is in_progress but tasks remain.")
        if lines or self.has_open_items():
            lines.append("")
            lines.append("Task list:")
            for t in self._items:
                marks = {
                    "pending": "[ ]",
                    "in_progress": "[->]",
                    "verifying": "[?]",
                    "verified": "[V]",
                    "escalated": "[!]",
                    "waived": "[-]",
                }
                mark = marks.get(t["status"], "[?]")
                att = f" (x{t['attempts']})" if t.get("attempts") else ""
                lines.append(f"  {mark} {t['content'][:70]}{att}")
            lines.append("")
            lines.append("Commands:")
            lines.append("  todowrite content=<task> status=in_progress  - start a task")
            lines.append("  todowrite content=<task> status=verifying    - mark done for verification")
            lines.append("  todowrite content=<task> status=verified     - confirm verified")
            lines.append("  todowrite content=<task> status=waived       - skip verification")
            lines.append("Do NOT stop while ANY item is pending or in_progress.")
            return "\n".join(lines)
        return None

    def stats(self) -> dict:
        """Return loop status, iteration, and per-status task counts."""
        by_status: dict[str, int] = {}
        for t in self._items:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        return {
            "status": self._status,
            "iteration": self._iteration,
            "max_iterations": self._max_iterations,
            "total_tasks": len(self._items),
            "by_status": by_status,
        }

    def reset(self) -> None:
        """Clear all tasks/state and remove the persisted state file."""
        self._items.clear()
        self._iteration = 0
        self._status = "open"
        if os.path.exists(self._state_path):
            try:
                os.remove(self._state_path)
            except Exception:
                logger.debug("todo_tracker: state file cleanup failed")

    def _find(self, content: str) -> dict | None:
        for t in self._items:
            if t["content"] == content:
                return t
        return None


class TodoRegister:
    """In-memory register of per-executor TodoTrackers (multi-AgentLoop view).

    Every AgentLoop execution body (L3A session loop, subagents, scouts)
    creates its own TodoTracker; the register keeps them all visible from
    one place so a Cell can see the cross-executor TODO table (agent_id →
    tasks) without touching the JSON state files. The register is pure
    memory — the JSON files remain the persistence layer (lossless across
    restarts); this layer is the fast shared view.
    """

    def __init__(self) -> None:
        self._trackers: dict[str, TodoTracker] = {}
        self._lock = threading.RLock()

    def register(self, agent_id: str, tracker: TodoTracker) -> bool:
        """Register an executor's tracker (first registration wins)."""
        with self._lock:
            if agent_id in self._trackers:
                return False
            self._trackers[agent_id] = tracker
            return True

    def get(self, agent_id: str) -> TodoTracker | None:
        """Return the tracker for an executor, or None."""
        with self._lock:
            return self._trackers.get(agent_id)

    def unregister(self, agent_id: str) -> bool:
        """Drop an executor's tracker."""
        with self._lock:
            return self._trackers.pop(agent_id, None) is not None

    def snapshot(self, agent_id: str = "") -> dict:
        """Aggregate TODO view: executor → status/iteration/task counts.

        Args:
            agent_id: filter to one executor when given.

        Returns:
            dict mapping executor id → its tracker.stats() (or summary).
        """
        with self._lock:
            ids = [agent_id] if agent_id else sorted(self._trackers.keys())
            out: dict[str, dict] = {}
            for aid in ids:
                tracker = self._trackers.get(aid)
                if tracker is not None:
                    out[aid] = tracker.stats()
            return out

    def clear(self) -> None:
        """Drop all trackers (tests / Cell teardown)."""
        with self._lock:
            self._trackers.clear()


_register: TodoRegister | None = None
_register_lock = threading.RLock()


def get_todo_register() -> TodoRegister:
    """Get the process-wide TodoRegister singleton."""
    global _register
    with _register_lock:
        if _register is None:
            _register = TodoRegister()
        return _register


def reset_todo_register() -> None:
    """Reset the TodoRegister singleton (tests / lifecycle)."""
    global _register
    with _register_lock:
        _register = None
