"""L3ADaemon implementation — daemon lifecycle, tick phases and singleton.

Extracted from ``l3a/__init__.py`` (the package init now only re-exports):
the context-source registry builders, the L3ADaemon class (persistent
process above Cell: session API, decision layer, delegation, maintenance
ticks) and the module-level singleton accessors live here.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_150
from l3.error_bus import capture

from . import api as _api
from . import archive as _archive
from . import params as _p
from .context import ContextRegistry, ContextSource
from .model import L3AModelConfig
from .session import Session, SessionManager

logger = logging.getLogger(__name__)


def _build_default_registry() -> ContextRegistry:
    reg = ContextRegistry()
    try:
        from l3.memory.central_memory import get_l3a_memory as _gm

        def _mem_loader():
            try:
                return _gm().build_context(_p.AGENT_ID, max_tokens=_p.MEMORY_MAX_TOKENS)
            except Exception:
                capture("l3a: memory context build failed", error_code="E_L3A_CTX", component="l3a")
                return ""

        reg.register(
            ContextSource(
                key="memory",
                loader=_mem_loader,
                render_baseline=lambda v: f"## Memory context\n{v}",
                render_update=lambda o, n: f"## Memory context (updated)\n{n}",
                render_removal=lambda: "## Memory context\n(no recent memory)",
            )
        )
    except Exception:
        capture("l3a: memory source registration skipped", error_code="E_L3A_CTX", component="l3a")
        logger.debug("l3a: memory source registration skipped")

    try:
        from l1.kernel.constitution import get_constitution as _gc

        reg.register(
            ContextSource(
                key="constitution",
                loader=lambda: _gc().summary(for_agent=_p.AGENT_ID),
                render_baseline=lambda v: f"## Rules\n{v}",
                render_update=lambda o, n: f"## Rules (updated)\n{n}",
            )
        )
    except Exception:
        capture("l3a: constitution source registration skipped", error_code="E_L3A_CTX", component="l3a")
        logger.debug("l3a: constitution source registration skipped")

    from datetime import datetime

    reg.register(
        ContextSource(
            key="system_time",
            loader=lambda: datetime.now(UTC).isoformat(),
            render_baseline=lambda v: f"## Current time\n{v}",
            render_update=lambda o, n: f"## Time updated\n{n}",
        )
    )

    reg.register(
        ContextSource(
            key="model_info",
            loader=lambda: _active_model.show(),
            render_baseline=lambda v: (
                f"## Active model\nProvider: {v.get('provider', '?')}  Model: {v.get('model', '?')}"
            ),
            render_update=lambda o, n: (
                f"## Model changed\nProvider: {o.get('provider', '?')} -> {n.get('provider', '?')}  Model: {o.get('model', '?')} -> {n.get('model', '?')}"
            ),
        )
    )

    reg.register(
        ContextSource(
            key="convergence",
            loader=lambda: _convergence_loader(),
            render_baseline=lambda v: _convergence_render(v),
            render_update=lambda o, n: _convergence_render(n),
        )
    )

    reg.register(
        ContextSource(
            key="l3a_memory",
            loader=lambda: _l3a_memory_loader(),
            render_baseline=lambda v: _l3a_memory_render(v),
            render_update=lambda o, n: _l3a_memory_render(n),
        )
    )

    return reg


def _l3a_memory_loader() -> list[dict]:
    """Load L3A's distilled deliberation summaries (bypass memory, latest 5)."""
    try:
        from .summaries import get_store

        return [s.to_dict() for s in get_store().latest(limit=5)]
    except Exception:
        capture("l3a: summaries loader failed", error_code="E_L3A_CTX", component="l3a")
        return []


def _l3a_memory_render(summaries: list[dict]) -> str:
    if not summaries:
        return "## L3A memory\n(no distilled deliberations yet)"
    lines = ["## L3A memory (recent deliberations)"]
    for s in summaries:
        lines.append(f"- [{s.get('issue_id', '?')}] {s.get('title', '')} (domain={s.get('domain', '')})")
        lines.append(f"  {s.get('summary', '')[:LOG_TRUNC_150]}")
    return "\n".join(lines)


def _convergence_loader() -> list[dict]:
    """Load pending convention/convergence items from all Cells."""
    try:
        from l3.cell import _cells
        from l3.discussion.cell_answer_repo import CellAnswerRepo

        items = []
        for cid in list(_cells.keys()):
            try:
                repo = CellAnswerRepo(cid, "")
                for a in repo.get_all():
                    items.append(
                        {
                            "cell": cid,
                            "agent_id": a.agent_id,
                            "phase": a.phase,
                            "type": a.answer_type,
                            "created_at": a.created_at,
                        }
                    )
            except Exception:
                capture(
                    "l3a: cell answer repo read failed",
                    error_code="E_L3A_CTX",
                    component="l3a",
                    context={"cell_id": cid},
                )
                continue
        return items
    except Exception:
        capture("l3a: convergence loader failed", error_code="E_L3A_CTX", component="l3a")
        return []


def _convergence_render(items: list[dict]) -> str:
    if not items:
        return "## Convergence\n(no active convention discussions)"
    lines = ["## Convergence (active deliberations)"]
    for it in items[:10]:
        lines.append(f"- [{it['cell']}] {it['agent_id']} phase={it['phase']} type={it['type']}")
    return "\n".join(lines)


_active_model = L3AModelConfig()


class L3ADaemon:
    """L3A daemon — persistent process above Cell.

    Lifecycle:
      start() → background daemon thread
      tick()  → auto-close idle sessions, maintenance
      stop()  → join thread
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None
        self.manager = SessionManager()
        # P0.6: rebuild active sessions from durable snapshots on boot —
        # idempotent, best-effort (failures log, never block daemon start).
        try:
            rec = self.manager.recover_from_store()
            if rec.get("recovered"):
                logger.info(
                    "l3a daemon: recovered %d session(s) from store: %s",
                    len(rec["recovered"]),
                    ",".join(rec["recovered"]),
                )
        except Exception:
            logger.debug("l3a daemon: session recovery skipped", exc_info=True)
        self.registry = _build_default_registry()
        self.model_config = _active_model
        self._pmu: Any = None
        self._sa_pool: Any = None
        self._secretary: Any = None
        self._init_pmu()
        self._init_subagent_pool()
        self._init_secretary()

    # ── Session API ──

    def _init_pmu(self) -> None:
        try:
            from l3.cell.components.cell_pmu import CellPmu

            self._pmu = CellPmu(cell_id="l3a")
        except Exception as e:
            capture("l3a: CellPmu init failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
            logger.debug("l3a: CellPmu init failed: %s", e)
            self._pmu = None

    def _init_subagent_pool(self) -> None:
        try:
            from .subagent import get_pool as _get_sa_pool

            self._sa_pool = _get_sa_pool()
        except Exception as e:
            capture(
                "l3a: subagent pool init failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)}
            )
            logger.debug("l3a: subagent pool init failed: %s", e)
            self._sa_pool = None

    def _init_secretary(self) -> None:
        """Mount the L3A-C secretary (C2): analysis/report + card co-production.

        The secretary records contributions and upgrades assist -> peer at
        the capability threshold; wiring it into the daemon lifecycle makes
        the L3A-C surface live (gated by settings ``l3a.secretary.enabled``,
        default on). Non-fatal on failure.
        """
        try:
            from l1.kernel.settings import get_settings

            from .secretary import get_secretary

            if not bool(get_settings().get("l3a.secretary.enabled", True)):
                logger.info("l3a: secretary disabled by settings")
                self._secretary = None
                return
            self._secretary = get_secretary()
            logger.info("l3a: L3A-C secretary mounted (threshold=%s)", getattr(self._secretary, "_threshold", "?"))
        except Exception as e:
            capture("l3a: secretary init failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
            logger.debug("l3a: secretary init failed: %s", e)
            self._secretary = None

    def create_session(self, title: str = "") -> Session:
        """Create a new session wired with the daemon's model config and PMU."""
        s = self.manager.create(title=title, model_config=self.model_config, registry=self.registry)
        if self._pmu:
            s.set_pmu(self._pmu)
        return s

    def decide(self, intent: str, domain: str = "", cell_count: int | None = None) -> dict:
        """L3A decision-center interpretation of a user intent ([13][16]).

        Interprets the intent via the generic three-identity matcher and
        suggests the owning department (L3A-assisted designation). This is
        the decision surface that turns L3A from a session bookkeeper into
        an intent-interpreting entity — the final department choice stays
        config-driven and user-settable.

        Args:
            intent: User intent / card title.
            domain: Optional card domain hint.
            cell_count: Optional Cell count (defaults to live count).

        Returns:
            Structured decision: identity match, suggested department,
            division-active flag.
        """
        try:
            from l3.bus.htn_planner import match_identity
            from l3.cell.department import get_department_manager, model_role_for, suggest_department

            identity = match_identity(intent, domain)
            suggestion = suggest_department(intent, domain)
            mgr = get_department_manager()
            return {
                "success": True,
                "intent": intent,
                "identity": identity,
                "department_suggestion": suggestion,
                "division_active": mgr.active(cell_count),
                "model_role": model_role_for(suggestion),  # 2.1-D4: executor for the suggested department
            }
        except Exception as e:
            capture("l3a: decide failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
            logger.debug("l3a: decide failed: %s", e)
            return {"success": False, "error": str(e), "department_suggestion": ""}

    def decision_layer(self, cell_count: int | None = None) -> str:
        """Report L3A's decision-layer role (D2).

        With fewer than 2 Cells L3A is the first decision-maker ("first").
        Once Cells reach the department threshold — and the secretary has
        upgraded to peer — L3A becomes the second decision layer
        ("second"): it commissions the secretary/decision bodies and
        executes L3-layer decision tools instead of being the single
        session bookkeeper.
        """
        try:
            from l1.kernel.params.agent import CELL_DEPARTMENT_MIN
            from l3.cell import get_cells

            if cell_count is None:
                cell_count = len(get_cells())
            secretary_peer = bool(self._secretary) and self._secretary.mode() == "peer"
            if cell_count >= CELL_DEPARTMENT_MIN and secretary_peer:
                return "second"
            return "first"
        except Exception as e:
            logger.debug("l3a: decision_layer failed: %s", e)
            return "first"

    def delegate(self, decision: str, target: str = "", spec: str = "secretary") -> dict:
        """Commission a decision task to a secretary/decision body (D2).

        Uses the subagent pool (or the secretary's peer session when
        available) so L3A delegates execution instead of running
        everything itself — the second-decision-layer mode.

        Args:
            decision: The decision/task description to delegate.
            target: Optional target (session id / scope); "" = auto.
            spec: Subagent spec name (default "secretary").

        Returns:
            The commission registration dict.
        """
        if self._sa_pool:
            try:
                return self._sa_pool.commission(spec=spec, task=decision, group="l3a-delegate")
            except Exception as e:
                logger.debug("l3a: delegate failed: %s", e)
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "subagent pool unavailable"}

    def get_session(self, session_id: str) -> Session | None:
        """Fetch an active session by id, or None when unknown."""
        return self.manager.get(session_id)

    def dispatch(self, args: list[str]) -> dict:
        """Route L2 shell args through the L3A command dispatcher and return its result dict."""
        return _api.dispatch(args, self.manager, self.registry, self.model_config)

    def archive_search(self, limit: int = 10, session_id: str | None = None) -> dict:
        """Search archived sessions and return their metadata entries."""
        return _archive.search_sessions(limit=limit, session_id=session_id)

    def archive_transcript(self, session_id: str) -> list[dict] | None:
        """Return the archived transcript for a session id, or None when absent."""
        return _archive.get_transcript(session_id)

    # ── Daemon lifecycle ──

    def start(self) -> dict:
        """Start the daemon thread and inject global LLM config, returning a result dict."""
        if self._running:
            return {"success": True, "note": "already running"}
        # Inject global LLM config before first session
        try:
            from l3.config.settings_center import get_center

            global_config = get_center().all()
            self.model_config.apply_global(global_config)
        except Exception:
            capture("l3a: global config injection failed", error_code="E_L3A_DAEMON", component="l3a")
            logger.debug("l3a: global config injection failed, using defaults")
        self._running = True
        # Propagate the spawn-time context (trace_id) into the daemon thread —
        # bare threads lose contextvars on Python 3.11.
        from l3.error_bus.core import propagate_context

        self._thread = threading.Thread(target=propagate_context(self._daemon_loop), daemon=True, name="l3a-daemon")
        self._thread.start()
        logger.info("L3A daemon started")
        try:
            from l3.bus.log import get_service as _ls

            _ls().info("L3A daemon started", service="l3a")
        except Exception:
            logger.debug("l3a: log service unavailable at start, skipped", exc_info=True)
        return {"success": True}

    def stop(self) -> dict:
        """Stop the daemon thread and subagent pool, returning a result dict."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=_p.DAEMON_STOP_TIMEOUT)
            self._thread = None
        if self._sa_pool:
            try:
                self._sa_pool.shutdown(wait=True)
            except Exception:
                capture("l3a: subagent pool shutdown failed", error_code="E_L3A_DAEMON", component="l3a")
                logger.debug("l3a: subagent pool shutdown failed")
        logger.info("L3A daemon stopped")
        try:
            from l3.bus.log import get_service as _ls

            _ls().info("L3A daemon stopped", service="l3a")
        except Exception:
            logger.debug("l3a: log service unavailable at stop, skipped", exc_info=True)
        return {"success": True}

    def _daemon_loop(self) -> None:
        while self._running:
            time.sleep(_p.DAEMON_TICK_INTERVAL)
            if not self._running:
                break
            try:
                self.tick()
            except Exception as e:
                capture("L3A daemon tick failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
                logger.error("L3A daemon tick failed: %s", e)

    def tick(self) -> dict:
        """Run one maintenance pass (PMU, task sync, auto-compress, idle close) and return a summary dict."""
        results: dict[str, Any] = {}
        self._tick_pmu()
        self._tick_tasks_sync(results)
        self._tick_auto_compress(results)
        self._tick_mer(results)
        self._tick_idle_close(results)
        self._tick_pool_elasticity(results)
        self._tick_governance(results)
        return results

    def _tick_pool_elasticity(self, results: dict) -> None:
        """D3 consumption point: adapt the subagent pool to task intensity.

        Uses the active-session count as the intensity signal; the pool's
        worker count follows it (bounded by params caps). Also records the
        evolved decision-body count (decision_bodies_for_intensity) so the
        decision-layer evolution has a live consumer. Non-fatal.
        """
        try:
            if not self._sa_pool:
                return
            active = len(self.manager.list_active())
            self._sa_pool.resize_for_intensity(active)
            results["pool_workers"] = self._sa_pool.max_workers()
            from l3.cell.peers.l3a.subagent import decision_bodies_for_intensity

            bodies = decision_bodies_for_intensity(active)
            results["decision_bodies"] = bodies
            # D3 consumption: materialize the evolved secretary instances
            # (each owning an isolated l3a-c-<n> memory scope). The base
            # secretary ("l3a") is the first body.
            from l3.cell.peers.l3a.secretary import get_or_create_secretary

            get_or_create_secretary("l3a")
            for i in range(1, bodies):
                get_or_create_secretary(f"l3a-c-{i}")
            results["secretary_scopes"] = [f"l3a-c-{i}" for i in range(1, bodies)]
        except Exception as e:
            logger.debug("l3a: pool elasticity skipped: %s", e)

    # ── Tick phases (split for readability; each is a self-contained stage) ──

    def _tick_pmu(self) -> None:
        """Push the PMU snapshot to StatsCenter."""
        if self._pmu:
            try:
                self._pmu.snapshot(force=True)
            except Exception as e:
                capture(
                    "l3a: PMU snapshot failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)}
                )
                logger.debug("l3a: PMU snapshot failed: %s", e)

    def _tick_tasks_sync(self, results: dict[str, Any]) -> None:
        """Watcher: reconcile session task tables with CardRegistry."""
        synced = 0
        for s in self.manager.list_active():
            sid = s.get("session_id", "")
            sess = self.manager.get(sid)
            if sess:
                try:
                    synced += sess.tasks.sync_from_registry()
                except Exception as e:
                    capture(
                        "l3a: task sync failed",
                        error_code="E_L3A_DAEMON",
                        component="l3a",
                        context={"session_id": sid, "error": str(e)},
                    )
                    logger.debug("l3a: task sync failed for %s: %s", sid, e)
        if synced:
            results["tasks_synced"] = synced

    def _tick_auto_compress(self, results: dict[str, Any]) -> None:
        """Auto-compression monitor: check context pressure per session."""
        auto_compressed = 0
        for s in self.manager.list_active():
            sid = s.get("session_id", "")
            sess = self.manager.get(sid)
            if not sess:
                continue
            try:
                r = sess.auto_compress_check()
                if r.get("action") == "compressed":
                    auto_compressed += 1
                    self._auto_compressions = getattr(self, "_auto_compressions", 0) + 1
                    results.setdefault("auto_compressed", []).append(
                        {
                            "session_id": sid,
                            "compressed": r.get("compressed", 0),
                            "pressure": r.get("pressure_before", 0),
                            "threshold": r.get("threshold", 0),
                        }
                    )
            except Exception as e:
                capture(
                    "l3a: auto-compress check failed",
                    error_code="E_L3A_DAEMON",
                    component="l3a",
                    context={"session_id": sid, "error": str(e)},
                )
                logger.debug("l3a: auto-compress failed for %s: %s", sid, e)
        if auto_compressed:
            results["auto_compressed_count"] = auto_compressed

    def _tick_mer(self, results: dict[str, Any]) -> None:
        """Mer bypass: periodically aggregate multi-agent R1-R3 → symbolic Mer graph → controlled entry into R4.

        Toggled by memory.mer.enabled; bypass failure does not affect the main flow.
        """
        try:
            from l3.memory.memory_mer import get_mer

            mer = get_mer()
            if mer.enabled:
                mr = mer.transform_and_archive()
                if mr.get("archived"):
                    results["mer_archived"] = mr["archived"]
                    results["mer_entries"] = mr.get("entries", 0)
        except Exception as e:
            capture("l3a: mer transform failed", error_code="E_L3A_DAEMON", component="l3a", context={"error": str(e)})
            logger.debug("l3a: mer transform failed: %s", e)

    def _tick_idle_close(self, results: dict[str, Any]) -> None:
        """Auto-close sessions idle beyond the configured timeout."""
        idle_timeout = _p.IDLE_TIMEOUT_DEFAULT
        try:
            from l3.config.settings_center import get_center

            idle_timeout = get_center().get("l3a.idle_timeout", _p.IDLE_TIMEOUT_DEFAULT)
        except Exception:
            capture("l3a: idle_timeout resolve failed", error_code="E_L3A_DAEMON", component="l3a")
            pass
        for s in self.manager.list_active():
            if s.get("status") != "active":
                continue
            last_active = s.get("last_active_at") or s.get("created_at", 0)
            idle = time.time() - last_active
            if idle > idle_timeout:
                sid = s.get("session_id", "")
                self.manager.close(sid)
                results.setdefault("auto_closed", []).append(sid)
                logger.info("L3A daemon: auto-closed idle session %s", sid)

    def _tick_governance(self, results: dict[str, Any]) -> None:
        """Governance metrics: emit summary via MonitorBus."""
        active_sessions = self.manager.list_active()
        if active_sessions:
            results["governance"] = {
                "active_sessions": len(active_sessions),
                "total_turns": sum(s.get("turn_count", 0) for s in active_sessions),
                "total_cards": sum(s.get("card_count", 0) for s in active_sessions),
            }
            try:
                from l3.bus.monitor_bus import MonitorEvent as MonitorEventCls
                from l3.bus.monitor_bus import get_bus as _mb

                _mb().emit(
                    MonitorEventCls(
                        type="l3a.governance",
                        source="l3a_daemon",
                        severity="info",
                        message=f"{results['governance']['active_sessions']} active sessions",
                        data=results["governance"],
                    )
                )
            except Exception:
                capture("l3a: governance event emit failed", error_code="E_L3A_DAEMON", component="l3a")
                logger.debug("l3a: governance event emit failed")


# ── Module-level singleton ──

_daemon: L3ADaemon | None = None
_daemon_lock = threading.Lock()


def get_daemon() -> L3ADaemon:
    """Return the process-wide L3ADaemon singleton, creating it on first use."""
    global _daemon
    if _daemon is None:
        with _daemon_lock:
            if _daemon is None:
                _daemon = L3ADaemon()
    return _daemon


def reset_daemon() -> None:
    """Reset the singleton L3ADaemon instance (for testing)."""
    global _daemon
    if _daemon:
        _daemon.stop()
    _daemon = None


def start() -> dict:
    """Start the global L3A daemon and return its start result dict."""
    return get_daemon().start()


def stop() -> dict:
    """Stop and clear the global L3A daemon, returning a result dict."""
    global _daemon
    if _daemon is None:
        return {"success": True, "note": "not running"}
    r = _daemon.stop()
    _daemon = None
    return r


def dispatch(args: list[str] | None = None) -> dict:
    """Dispatch L3A shell args through the global daemon and return the result dict."""
    return get_daemon().dispatch(args or [])
