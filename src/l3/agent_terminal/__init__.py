"""AgentTerminal — persistent background terminal process for one Agent.

Extracted from:
  - _term_types.py: TerminalStatus, CardMode, TerminalCard, CardResult
  - _term_handlers.py: handler registry, default handlers, _HANDLER_MAP
"""

from __future__ import annotations

import logging
import os as _os
import threading
import time
import uuid
from collections import OrderedDict, deque
from typing import Any

from l1.kernel import emit_signal, get_event_bus
from l1.kernel.allocator import get_allocator
from l1.kernel.constitution import get_constitution
from l1.kernel.params.agent import (
    AGENT_CLEARANCE,
    AGENT_LOOP_DEFAULT_STEPS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    AGENT_TERMINAL_MAX_SCOUTS,
    AGENT_TERMINAL_STDERR_MAX,
    AGENT_TERMINAL_STDIN_MAX,
    AGENT_TERMINAL_STDOUT_MAX,
    AGENT_TERMINAL_WORKER_JOIN_TIMEOUT,
    CARD_WAIT_TIMEOUT,
    DEFAULT_AGENT_CONFIGS,
    EVENT_REVIEW_REQUESTED,
    TERMINAL_MAX_WORKERS,
)
from l1.kernel.params.kernel import RING_1
from l1.kernel.params.system import (
    HASH_TRUNC_SHORT,
    LOG_TRUNC_80,
    LOG_TRUNC_200,
    LOG_TRUNC_500,
    POLL_INTERVAL_SLOW,
    SESSION_AUTO_RELOAD_ENABLED_DEFAULT,
    SESSION_MONITOR_ENABLED_DEFAULT,
)
from l3.params import SCOUT_COLLECT_TIMEOUT
from l3.services.model_service import get_service as _get_model_service

from ..agent._term_lifecycle import run_cache_keepalive  # noqa: F401  (re-export)
from ..agent._term_types import CardMode, CardResult, TerminalCard, TerminalStatus  # noqa: F401  (CardMode re-export)
from ..agent.scout import get_pool as get_scout_pool
from ..memory.cache import get_context_register, get_file_cache
from .card_execution import CardExecutionMixin
from .worker_pool import WorkerPoolMixin

logger = logging.getLogger(__name__)

_PROJECT_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))

_MODEL_SPEC = "peer_agent"


class AgentTerminal(CardExecutionMixin, WorkerPoolMixin):
    """Persistent background terminal process for one Agent."""

    def __init__(
        self,
        agent_id: str,
        role: str = "",
        territory: list[str] | None = None,
        cell_id: str = "",
        project_root: str = "",
    ):
        self.agent_id = agent_id
        self.role = role
        self.territory = territory or []
        self.cell_id = cell_id
        self._project_root = project_root or _PROJECT_ROOT
        # Session/process dual identity (3.3): process_id pins the backing
        # OS process (host pid — terminals are worker pools inside it);
        # session_id is bound lazily via register_session() for
        # unique, trackable session entities.
        import os

        self.process_id = os.getpid()
        self.session_id = ""
        # P0.2: a terminal backs a SET of sessions — registering an extra
        # session must never overwrite an existing binding (release-blocking
        # defect: two sessions silently stole one terminal's session_id).
        self._bound_sessions: set[str] = set()

        cfg = DEFAULT_AGENT_CONFIGS.get(role) if role else None
        self.ring = cfg.ring if cfg else AGENT_CLEARANCE.get(role, 1)
        self.max_scouts = cfg.max_scouts if cfg else AGENT_TERMINAL_MAX_SCOUTS
        # model_config: resolve from ThinkQuotaRegistry (global → cell → agent)
        self.model_config = None
        try:
            from ..scheduler.think_registry import get_think_registry

            reg = get_think_registry()
            self.model_config = (
                reg.resolve(
                    cell_id,
                    agent_id,
                    agent_model_config=cfg.model_config if cfg else None,
                )
                or None
            )
        except Exception:
            # Fallback: use config defaults directly
            self.model_config = cfg.model_config if cfg and cfg.model_config else None
        self.system_prompt_key = cfg.system_prompt_key if cfg and cfg.system_prompt_key else ""
        self.status = TerminalStatus.BOOTING
        self.bus = get_event_bus()
        self.constitution = get_constitution()
        self.allocator = get_allocator()
        self.scout_pool = get_scout_pool()
        self.file_cache = get_file_cache(cell_id)
        self.context = get_context_register(cell_id)

        self.stdin: deque[TerminalCard] = deque(maxlen=AGENT_TERMINAL_STDIN_MAX)
        self.stdout: deque[CardResult] = deque(maxlen=AGENT_TERMINAL_STDOUT_MAX)
        self.stderr: deque[str] = deque(maxlen=AGENT_TERMINAL_STDERR_MAX)
        self._pending: dict[str, threading.Event] = {}
        self._results: OrderedDict[str, CardResult] = OrderedDict()
        self._lock = threading.RLock()
        self._running = False
        self._workers: list[threading.Thread] = []
        self._max_workers = TERMINAL_MAX_WORKERS
        self._boot_result: dict = {}
        self._convention_loops: dict[str, Any] = {}
        self._cards_processed = 0
        self._active_cards = 0
        self._async_scouts: dict[str, dict] = {}
        self._async_pending: set[str] = set()
        self._async_scout_events: dict[str, threading.Event] = {}
        self._async_scout_count = 0
        self._tool_registry: dict[str, Any] | None = None
        from l1.kernel.params.agent import TERMINAL_MODE_DEFAULT, TERMINAL_STATE_DEFAULT

        self._loop_mode: str = TERMINAL_MODE_DEFAULT
        self._loop_state: str = TERMINAL_STATE_DEFAULT
        self._paused: bool = False
        self._reload_count: int = 0  # anomaly auto-reloads (3.3, P0-③)
        # Persistent AgentLoop — reuse across cards for conversational continuity
        self._persistent_loop: bool = False
        self._active_loop: Any = None
        self._active_loop_lock: Any = threading.Lock()
        # Card timeout guard — interrupt stuck cards
        self._card_timeout: float = 0.0
        self._card_deadline: float = 0.0
        self._current_card: str = ""
        self._cards_since_pressure_check: int = 0
        # ── AgentLoop instance budget (reserved, not yet enforced) ──
        from l1.kernel.params.agent import TERMINAL_MAX_CONCURRENT_LOOPS

        self._max_concurrent_loops: int = TERMINAL_MAX_CONCURRENT_LOOPS
        self._active_loops: int = 0
        from ..services.todo import TodoTable

        self.todo = TodoTable(agent_id)
        # Watchdog pet callback (set by Cell)
        self._watchdog_pet: Any = None
        # PMU reference (set by Cell._inject_tools)
        self._pmu: Any = None

    def set_max_workers(self, count: int) -> dict:
        """Dynamically adjust the max worker thread count.

        If the terminal is already running and *count* exceeds the current
        worker count, additional worker threads are spawned immediately.
        Reduced counts take effect as workers finish their current card.
        """
        self._max_workers = max(1, count)
        if self._running:
            current = len([w for w in self._workers if w.is_alive()])
            for i in range(current, self._max_workers):
                w = threading.Thread(target=self._worker, daemon=True, name=f"term-{self.agent_id}-w{i}")
                w.start()
                self._workers.append(w)
        return {"success": True, "max_workers": self._max_workers}

    def set_pmu(self, pmu: Any) -> None:
        """Attach the PMU reference used for tool injection."""
        self._pmu = pmu

    def set_tool_registry(self, registry: dict[str, Any]) -> None:
        """Attach the tool registry used for tool listing."""
        self._tool_registry = registry

    def set_watchdog_pet(self, fn: Any) -> None:
        """Set the watchdog pet callback, called after each card completes."""
        self._watchdog_pet = fn

    def list_tools(self) -> list[dict]:
        """List tools available to this terminal, filtered by ring and muting."""
        if not self._tool_registry:
            return []
        from l1.kernel.params.kernel import RING_NUM_MAP as _RNM
        from l3.tool_system.tool_spec import is_muted as _is_muted

        tools = []
        for name, spec in self._tool_registry.items():
            sr = getattr(spec, "ring", RING_1)
            if self.ring >= _RNM.get(sr, 1) and not _is_muted(name):
                tools.append(
                    {
                        "name": name,
                        "ring": sr,
                        "danger": getattr(spec, "danger", 0),
                        "description": getattr(spec, "description", "")[:LOG_TRUNC_80],
                    }
                )
        return sorted(tools, key=lambda t: (t["ring"], t["name"]))

    def _issue_card(self, card: TerminalCard) -> CardResult:
        emit_signal(
            EVENT_REVIEW_REQUESTED,
            sender=self.agent_id,
            target="cell",
            data={
                "type": "issue",
                "action": card.action,
                "target": card.target,
                "params": card.params,
                "card_id": card.card_id,
                "proposed_by": self.agent_id,
            },
        )
        return CardResult(
            card_id=card.card_id,
            action=card.action,
            success=True,
            output=f"issue created: {card.action}",
            phase=["issue"],
        )

    # ── Todo Table API ──

    def add_todo(self, intent: str, domain: str = "", priority: int = 5, depends_on: list[str] | None = None) -> str:
        """Add a todo entry; returns the new todo id."""
        tid = self.todo.add(intent, domain, priority, depends_on)
        with self._lock:
            if self.status in (TerminalStatus.IDLE,):
                self.status = TerminalStatus.PROCESSING
        return tid

    def list_todos(self, status: str = "", limit: int = 20) -> list[dict]:
        """List todos, optionally filtered by status, up to *limit* entries."""
        from ..services.todo import TodoStatus

        st = TodoStatus[status.upper()] if status else None
        return self.todo.list(st, limit)

    def cancel_todo(self, todo_id: str) -> bool:
        """Cancel a todo entry; returns True on success."""
        return self.todo.cancel(todo_id)

    def todo_stats(self) -> dict:
        """Return todo table statistics."""
        return self.todo.stats()

    # ── External API ──

    def dispatch(self, card: TerminalCard) -> str:
        """Queue a card for execution; returns the card id."""
        with self._lock:
            self.add_todo(f"{card.action} {card.target}", priority=3)
            self.stdin.append(card)
            if self.status in (TerminalStatus.IDLE,):
                self.status = TerminalStatus.PROCESSING
        return card.card_id

    def wait_for_result(self, card_id: str, timeout: float = CARD_WAIT_TIMEOUT) -> CardResult | None:
        """Block until the card result is ready or *timeout* elapses."""
        event = threading.Event()
        with self._lock:
            if card_id in self._results:
                return self._results[card_id]
            self._pending[card_id] = event
        event.wait(timeout=timeout)
        with self._lock:
            return self._results.get(card_id)

    def read_stdout(self, clear: bool = True) -> list[CardResult]:
        """Read accumulated stdout results, optionally clearing them."""
        with self._lock:
            r = list(self.stdout)
            if clear:
                self.stdout.clear()
            return r

    def read_stderr(self, clear: bool = True) -> list[str]:
        """Read accumulated stderr messages, optionally clearing them."""
        with self._lock:
            r = list(self.stderr)
            if clear:
                self.stderr.clear()
            return r

    # ── Convention handler (persistent AgentLoop per convention) ──

    def _convention_handler(self, card: TerminalCard) -> CardResult:
        from ..agent._term_convention import convention_handler as _ch

        return _ch(self, card)

    # ── Direct message handler ──

    def _handle_direct(self, card: TerminalCard) -> CardResult:
        """Handle direct message via stdin queue. Runs AgentLoop, writes to Memory R2."""
        from ..agent.agent_loop import AgentLoop

        text = card.params.get("text", "")
        sender = card.params.get("sender", "shell")
        from l1.kernel.prompts import get_prompt as _get_prompt

        loop = AgentLoop(
            task=text,
            agent_id=self.agent_id,
            system=_get_prompt("agent_terminal.direct").format(
                agent_id=self.agent_id,
                role=self.role,
            ),
            cell_id=self.cell_id,
        )
        result = loop.run(
            max_steps=AGENT_LOOP_DEFAULT_STEPS,
            timeout=AGENT_LOOP_DEFAULT_TIMEOUT,
            **_get_model_service().resolve_dict(_MODEL_SPEC),
        )
        answer = result.get("answer", "")
        try:
            from ..memory.memory import get_memory

            get_memory().remember(
                agent_id=self.agent_id,
                entry_type="direct_message",
                content=f"{sender}: {text[:LOG_TRUNC_200]}\nAgent: {answer[:LOG_TRUNC_500]}",
                tags=["direct_session"],
                ring=2,
            )
        except Exception:
            logger.debug("agent_terminal: direct message remember failed")
        return CardResult(card_id=card.card_id, action="direct_message", success=True, output=answer)

    def spawn_scout_async(self, template: str, scope: dict | None = None) -> dict:
        """Spawn a scout in the background; returns an ack with scout_id."""
        scout_id = f"async-{self.agent_id}-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        with self._lock:
            if self._async_scout_count >= self.max_scouts:
                return {"success": False, "error": f"max async scouts ({self.max_scouts})"}
            self._async_scout_count += 1
            self._async_pending.add(scout_id)
        threading.Thread(target=self._run_async_scout, args=(scout_id, template, scope or {}), daemon=True).start()
        return {"success": True, "scout_id": scout_id, "async": True}

    def _run_async_scout(self, scout_id: str, template: str, scope: dict) -> None:
        try:
            result = self.scout_pool.commission(self.agent_id, template, scope)
        except Exception as e:
            result = {"success": False, "error": str(e)}
        with self._lock:
            self._async_scouts[scout_id] = result
            self._async_pending.discard(scout_id)
            ev = self._async_scout_events.pop(scout_id, None)
            if ev:
                ev.set()
            self._async_scout_count = max(0, self._async_scout_count - 1)

    def collect_scout(self, scout_id: str, timeout: float = SCOUT_COLLECT_TIMEOUT) -> dict:
        """Collect an async scout result, waiting up to *timeout* seconds."""
        event = threading.Event()
        with self._lock:
            if scout_id in self._async_scouts:
                return self._async_scouts.pop(scout_id)
            self._async_scout_events[scout_id] = event
        event.wait(timeout=timeout)
        with self._lock:
            return self._async_scouts.pop(scout_id, {"success": False, "error": "timeout"})

    def collect_all_scouts(self, timeout: float = SCOUT_COLLECT_TIMEOUT) -> list[dict]:
        """Collect all pending async scout results, waiting up to *timeout*."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if not self._async_pending:
                    return [self._async_scouts.pop(sid) for sid in list(self._async_scouts.keys())]
            time.sleep(POLL_INTERVAL_SLOW)
        with self._lock:
            ids = list(self._async_scouts.keys())
            results = [self._async_scouts.pop(sid) for sid in ids]
            self._async_pending.clear()
            return results

    def set_persistent_loop(self, enabled: bool = True) -> dict:
        """Enable or disable persistent AgentLoop mode.

        When enabled, the AgentTerminal reuses the same AgentLoop instance
        across multiple cards, preserving LLM conversational context.
        Call ``reset_persistent_loop()`` to force a fresh start.
        """
        self._persistent_loop = enabled
        logger.info("agent %s: persistent_loop=%s", self.agent_id, enabled)
        return {"success": True, "persistent_loop": enabled}

    def reset_persistent_loop(self) -> dict:
        """Force-reset the persistent AgentLoop, discarding accumulated context."""
        with self._active_loop_lock:
            if self._active_loop is not None:
                self._active_loop._context_trail = None
            self._active_loop = None
        logger.info("agent %s: persistent loop reset", self.agent_id)
        return {"success": True, "action": "persistent_loop_reset"}

    def set_card_timeout(self, timeout: float) -> dict:
        """Set per-card execution timeout in seconds (0 = disabled)."""
        self._card_timeout = timeout
        logger.info("agent %s: card_timeout=%.1fs", self.agent_id, timeout)
        return {"success": True, "card_timeout": timeout}

    def set_mode(self, mode: str) -> dict:
        """Set the loop mode; returns success or a validation error."""
        from l1.kernel.params.agent import TERMINAL_MODE_VALID

        valid = TERMINAL_MODE_VALID
        if mode not in valid:
            return {"success": False, "error": f"mode must be one of {valid}"}
        self._loop_mode = mode
        return {"success": True, "mode": mode}

    def pause(self) -> dict:
        """Pause the terminal; blocks card processing."""
        self._paused = True
        self.status = TerminalStatus.BLOCKED
        return {"success": True, "paused": True}

    def resume(self) -> dict:
        """Resume the terminal after a pause."""
        self._paused = False
        self.status = TerminalStatus.IDLE
        return {"success": True, "resumed": True}

    def monitor_state(self) -> dict:
        """Real-time state for the session monitor (3.3, P0-②).

        Returns running status, resource/progress counters, and the dual
        identity (session_id + process_id) — feed for session_monitor().

        Returns:
            dict with status/running/cards/paused + dual identity.
        """
        with self._lock:
            bound = sorted(self._bound_sessions)
            cards = self._cards_processed
            active = self._active_cards
            paused = self._paused
            running = self._running
            status_name = self.status.name if hasattr(self.status, "name") else str(self.status)
        return {
            "session_id": self.session_id,
            "session_ids": bound,
            "process_id": self.process_id,
            "agent_id": self.agent_id,
            "status": status_name,
            "running": running,
            "cards_processed": cards,
            "active_cards": active,
            "paused": paused,
        }

    def auto_reload(self, reason: str = "") -> dict:
        """Session-level auto reload on anomaly (3.3, P0-③).

        Distinct from interrupt resume: this fully resets the session
        entity — stops workers, drops the active loop, REBUILDS the worker
        pool, and restores a reachable state. Restoration is verified:
        workers that ignore the join deadline fail the reload loudly
        (status BLOCKED, success False) instead of reporting a fake IDLE.

        Args:
            reason: anomaly reason (e.g. stagnation pattern).

        Returns:
            dict with success flag, reload count, worker count, and the
            reached status.
        """
        # Serialize against dispatch/shutdown that mutate _workers/_running.
        with self._lock:
            self._running = False
            stuck: list[str] = []
            # Copy to avoid mutation during join.
            workers_snapshot = list(self._workers)
            for w in workers_snapshot:
                w.join(timeout=AGENT_TERMINAL_WORKER_JOIN_TIMEOUT)
                if w.is_alive():
                    stuck.append(w.name)
            with self._active_loop_lock:
                self._active_loop = None
            self._active_cards = 0
            self._paused = False
            self._current_card = ""
            self._card_deadline = 0.0
            from l1.kernel.params.agent import TERMINAL_STATE_DEFAULT as _T_STATE

            self._loop_state = _T_STATE
            # Rebuild: keep only live threads, then top the pool back up so a
            # reloaded terminal actually accepts cards again.
            self._workers = [w for w in self._workers if w.is_alive()]
            self._running = True
            for i in range(max(0, self._max_workers - len(self._workers))):
                w = threading.Thread(
                    target=self._worker, daemon=True, name=f"term-{self.agent_id}-r{self._reload_count}-w{i}"
                )
                w.start()
                self._workers.append(w)
            self._reload_count += 1
            if stuck:
                self.status = TerminalStatus.BLOCKED
                logger.error(
                    "agent_terminal %s: auto_reload #%d INCOMPLETE (%s) — stuck workers: %s",
                    self.agent_id,
                    self._reload_count,
                    reason or "anomaly",
                    ",".join(stuck),
                )
                return {
                    "success": False,
                    "error": f"reload incomplete — {len(stuck)} worker(s) missed the join deadline",
                    "stuck_workers": stuck,
                    "agent_id": self.agent_id,
                    "reload_count": self._reload_count,
                    "status": "BLOCKED",
                    "reason": reason,
                }
            self.status = TerminalStatus.IDLE
            logger.info(
                "agent_terminal %s: auto_reload #%d (%s)", self.agent_id, self._reload_count, reason or "anomaly"
            )
            return {
                "success": True,
                "agent_id": self.agent_id,
                "reload_count": self._reload_count,
                "status": "IDLE",
                "workers": len(self._workers),
                "reason": reason,
            }

    def shutdown(self) -> dict:
        """Stop the terminal, join workers, and emit session_end hooks."""
        self._running = False
        for w in self._workers:
            w.join(timeout=AGENT_TERMINAL_WORKER_JOIN_TIMEOUT)
        # Clean up any orphaned convention loops
        for _conv_id, session in list(self._convention_loops.items()):
            loop_obj = session.get("loop")
            if loop_obj:
                try:
                    loop_obj.task = "Convention closed by agent shutdown."
                except Exception:
                    logger.debug("agent_terminal: convention loop cleanup failed")
        self._convention_loops.clear()
        self._results.clear()
        self.status = TerminalStatus.STOPPED
        # Lifecycle hook chain: session_end (agent session terminated)
        try:
            from l3.services.hook import get_hook_chain as _get_hc

            _get_hc().session_end(
                {"agent_id": self.agent_id, "cards_processed": self._cards_processed, "status": "stopped"}
            )
        except Exception as e:
            logger.debug("agent_terminal: session_end hook emit failed: %s", e)
        return {"success": True, "agent_id": self.agent_id, "cards_processed": self._cards_processed}

    def session_reachable(self) -> dict:
        """Check if this agent can accept a direct message (via stdin queue)."""
        if not self._running:
            return {"reachable": False, "reason": "not_running"}
        if self.status in (TerminalStatus.CRASHED, TerminalStatus.STOPPED):
            return {"reachable": False, "reason": self.status.name.lower()}
        return {"reachable": True, "reason": "ready", "queue_depth": len(self.stdin) if hasattr(self, "stdin") else 0}

    def send_direct_message(self, text: str, sender: str = "shell") -> dict:
        """Queue a direct message as a TerminalCard via stdin."""
        from ..agent._term_types import CardMode as TermCardMode
        from ..agent._term_types import TerminalCard

        card = TerminalCard(
            mode=TermCardMode.EXECUTE,
            action="direct_message",
            target=f"direct-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}",
            params={"text": text, "sender": sender},
            sender=sender,
        )
        cid = self.dispatch(card)
        return {"success": True, "card_id": cid}

    def status_report(self) -> dict:
        """Return a snapshot of terminal status and counters."""
        with self._lock:
            return {
                "agent_id": self.agent_id,
                "role": self.role,
                "ring": self.ring,
                "status": self.status.name,
                "cards_processed": self._cards_processed,
                "alive": self._running,
                "active_cards": self._active_cards,
                "mode": self._loop_mode,
                "loop_state": self._loop_state,
                "paused": self._paused,
                "current_card": self._current_card,
            }


# ── Factory ──

_terminals: dict[str, AgentTerminal] = {}
_terminals_lock = threading.Lock()


def get_terminal(agent_id: str, role: str = "", territory: list[str] | None = None, cell_id: str = "") -> AgentTerminal:
    """Return the shared terminal for *agent_id*, creating it on first use."""
    with _terminals_lock:
        if agent_id not in _terminals:
            _terminals[agent_id] = AgentTerminal(agent_id, role, territory, cell_id)
    return _terminals[agent_id]


def get_terminals() -> dict[str, AgentTerminal]:
    """Return a copy of all registered terminals keyed by agent id."""
    with _terminals_lock:
        return dict(_terminals)


def reset_terminals() -> None:
    """Shut down and clear all registered terminals."""
    with _terminals_lock:
        for t in list(_terminals.values()):
            t.shutdown()
        _terminals.clear()
    # Full agent-terminal reset: also drop the session registry, monitor
    # switch, and auto-reload switch (one _RESETS entry covers all).
    reset_sessions()
    reset_session_monitor()
    reset_auto_reload()


# ── Session monitor switch (3.3, P0-②) ──
# Operator-gated (API /api/v2/session-monitor + L2 /session monitor),
# default ON.
_session_monitor_state: dict = {"enabled": SESSION_MONITOR_ENABLED_DEFAULT}
_session_monitor_lock = threading.RLock()


def session_monitor_status() -> dict:
    """Return the session-monitor switch state."""
    with _session_monitor_lock:
        return {"enabled": bool(_session_monitor_state["enabled"])}


def set_session_monitor(enabled: bool | None = None) -> dict:
    """Set the session-monitor operator switch.

    Args:
        enabled: master switch (None = keep current). Default ON.

    Returns:
        dict with success flag and the effective switch.
    """
    with _session_monitor_lock:
        if enabled is not None:
            _session_monitor_state["enabled"] = bool(enabled)
        return {"success": True, **session_monitor_status()}


def reset_session_monitor() -> None:
    """Reset the session-monitor switch (tests / lifecycle)."""
    with _session_monitor_lock:
        _session_monitor_state["enabled"] = SESSION_MONITOR_ENABLED_DEFAULT


def session_monitor() -> dict:
    """Real-time status of every registered session entity (3.3, P0-②).

    Aggregates each bound session's monitor state — running status,
    resource/progress counters (cards processed, active cards, paused),
    and the dual identity (session_id + process_id). Feed for the
    /api/v2/session-monitor endpoint + L2 /session monitor (default ON).

    Returns:
        dict with success flag, session count, and per-session states.
    """
    with _session_monitor_lock:
        enabled = bool(_session_monitor_state["enabled"])
    if not enabled:
        return {"success": True, "count": 0, "sessions": [], "disabled": True}
    with _session_registry_lock:
        records = list(_session_registry.values())
    states: list[dict] = []
    for rec in records:
        terminal = rec.get("terminal")
        if terminal is None:
            continue
        states.append(terminal.monitor_state())
    return {"success": True, "count": len(states), "sessions": states}


# ── Session auto-reload (3.3, P0-③) ──
# On anomaly (e.g. stagnation), the session entity auto-reloads — distinct
# from interrupt resume. Operator switch (API + L2), default ON.
_auto_reload_state: dict = {"enabled": SESSION_AUTO_RELOAD_ENABLED_DEFAULT}
_auto_reload_lock = threading.RLock()


def auto_reload_status() -> dict:
    """Return the auto-reload switch state."""
    with _auto_reload_lock:
        return {"enabled": bool(_auto_reload_state["enabled"])}


def set_auto_reload(enabled: bool | None = None) -> dict:
    """Set the auto-reload operator switch.

    Args:
        enabled: master switch (None = keep current). Default ON.

    Returns:
        dict with success flag and the effective switch.
    """
    with _auto_reload_lock:
        if enabled is not None:
            _auto_reload_state["enabled"] = bool(enabled)
        return {"success": True, **auto_reload_status()}


def reset_auto_reload() -> None:
    """Reset the auto-reload switch (tests / lifecycle)."""
    with _auto_reload_lock:
        _auto_reload_state["enabled"] = SESSION_AUTO_RELOAD_ENABLED_DEFAULT


def auto_reload_session(agent_id: str, reason: str = "") -> dict:
    """Auto-reload an agent's session entity on anomaly (3.3, P0-③).

    Finds the terminal backing *agent_id* and triggers ``auto_reload``
    (full session reset — distinct from interrupt resume). No-op when the
    switch is off or no terminal is registered.

    Args:
        agent_id: the Peer Agent whose session entity reloads.
        reason: anomaly reason (e.g. stagnation pattern).

    Returns:
        dict with success flag and the reload result (or a no-op note).
    """
    with _auto_reload_lock:
        enabled = bool(_auto_reload_state["enabled"])
    if not enabled:
        return {"success": False, "error": "auto-reload disabled"}
    terminal = _terminals.get(agent_id)
    if terminal is None:
        return {"success": False, "error": f"no terminal for {agent_id}"}
    return terminal.auto_reload(reason=reason)


def on_stagnation(result: dict, agent_id: str) -> dict:
    """Wire StagnationDetector.check() results into auto-reload.

    When the detector reports ``{"stagnant": True, "pattern": ...}`` the
    session entity reloads automatically (reason = pattern); clean results
    are a no-op.

    Args:
        result: the detector's check() return dict.
        agent_id: the checked agent.

    Returns:
        dict with success flag and the reload outcome (or a no-op note).
    """
    if not (result or {}).get("stagnant"):
        return {"success": True, "reloaded": False, "note": "no stagnation"}
    pattern = str((result or {}).get("pattern", "unknown"))
    return auto_reload_session(agent_id, reason=f"stagnation:{pattern}")


# ── Session management registry (3.3, P0-①) ──
# Dual identity: every session entity is tracked by session_id AND its
# backing process_id, so a Cell's 3 Peer Agent sessions stay unique and
# traceable (session_id ↔ process_id ↔ terminal instance).
_session_registry: dict[str, dict] = {}
_session_registry_lock = threading.Lock()


def _primary_bound(terminal) -> str:
    """Return the deterministic primary session_id for a terminal."""
    return sorted(terminal._bound_sessions)[0] if terminal._bound_sessions else ""


def register_session(session_id: str, agent_id: str, meta: dict | None = None) -> dict:
    """Bind a session_id to its backing terminal (dual identity).

    Creates/attaches the agent's terminal and records
    ``{session_id, process_id, agent_id, state, bound_at, meta, terminal}``.
    Bindings are ADDITIVE — a terminal backs a set of sessions, so a new
    registration never overwrites an existing one. Returns the record
    (or an error dict when the session_id is already bound).

    Args:
        session_id: the session entity id (unique, trackable).
        agent_id: the backing Peer Agent (terminal owner).
        meta: identity payload preserved on the record
            (user_id / role / cell_id / memory_scope).

    Returns:
        dict with success flag and the session record.
    """
    with _session_registry_lock:
        if session_id in _session_registry:
            return {"success": False, "error": f"session {session_id} already registered"}
        terminal = get_terminal(agent_id, cell_id=str((meta or {}).get("cell_id", "")))
        terminal._bound_sessions.add(session_id)
        if not terminal.session_id:
            terminal.session_id = session_id
        record = {
            "session_id": session_id,
            "process_id": terminal.process_id,
            "agent_id": agent_id,
            "state": "active",
            "bound_at": time.time(),
            "meta": dict(meta or {}),
            "terminal": terminal,
        }
        _session_registry[session_id] = record
        return {"success": True, **{k: v for k, v in record.items() if k != "terminal"}}


def detach_session(session_id: str) -> dict:
    """Detach a session from its terminal without dropping the record.

    The registry entry flips to ``state="detached"`` and the session id is
    removed from the terminal's bound set; history stays queryable.

    Args:
        session_id: the session entity id.

    Returns:
        dict with success flag (False when unknown or already closed).
    """
    with _session_registry_lock:
        rec = _session_registry.get(session_id)
        if rec is None:
            return {"success": False, "error": f"session {session_id} not found"}
        if rec.get("state") == "closed":
            return {"success": False, "error": f"session {session_id} already closed"}
        rec["state"] = "detached"
        rec["detached_at"] = time.time()
        terminal = rec.get("terminal")
        if terminal is not None:
            terminal._bound_sessions.discard(session_id)
            if terminal.session_id == session_id:
                terminal.session_id = _primary_bound(terminal)
        return {"success": True, "session_id": session_id, "state": "detached"}


def close_session_binding(session_id: str) -> bool:
    """Mark a session binding closed and release its terminal slot.

    Called from the Session lifecycle (close) — the record flips to
    ``state="closed"``, the id leaves the terminal's bound set.

    Args:
        session_id: the session entity id.

    Returns:
        True when an active/detached binding was closed.
    """
    with _session_registry_lock:
        rec = _session_registry.get(session_id)
        if rec is None or rec.get("state") == "closed":
            return False
        rec["state"] = "closed"
        rec["closed_at"] = time.time()
        terminal = rec.get("terminal")
        if terminal is not None:
            terminal._bound_sessions.discard(session_id)
            if terminal.session_id == session_id:
                terminal.session_id = _primary_bound(terminal)
        return True


def get_session(session_id: str) -> dict:
    """Return a session record (without the terminal instance)."""
    with _session_registry_lock:
        rec = _session_registry.get(session_id)
        if rec is None:
            return {"success": False, "error": f"session {session_id} not found"}
        return {
            "success": True,
            "session_id": rec["session_id"],
            "process_id": rec["process_id"],
            "agent_id": rec["agent_id"],
            "state": rec.get("state", "active"),
            "meta": dict(rec.get("meta", {})),
        }


def list_sessions(include_closed: bool = False) -> dict:
    """List all registered session entities (id + process_id + agent)."""
    with _session_registry_lock:
        rows = [
            {
                "session_id": r["session_id"],
                "process_id": r["process_id"],
                "agent_id": r["agent_id"],
                "state": r.get("state", "active"),
            }
            for r in _session_registry.values()
            if include_closed or r.get("state", "active") != "closed"
        ]
        return {"success": True, "sessions": rows}


def unregister_session(session_id: str) -> bool:
    """Drop a session binding entirely (teardown; legacy API)."""
    with _session_registry_lock:
        rec = _session_registry.pop(session_id, None)
    if rec is None:
        return False
    terminal = rec.get("terminal")
    if terminal is not None:
        terminal._bound_sessions.discard(session_id)
        if terminal.session_id == session_id:
            terminal.session_id = _primary_bound(terminal)
    return True


def reset_sessions() -> None:
    """Clear the session registry and every terminal's bound-session set."""
    with _session_registry_lock:
        for rec in _session_registry.values():
            terminal = rec.get("terminal")
            if terminal is not None:
                terminal._bound_sessions.discard(rec["session_id"])
                if terminal.session_id == rec["session_id"]:
                    terminal.session_id = _primary_bound(terminal)
        _session_registry.clear()
