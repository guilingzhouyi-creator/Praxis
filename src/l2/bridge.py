"""L2 → L3 command bridge — the single L3 boundary for the L2 shell.

Every shell-command access to L3 internals funnels through this module so
the L2→L3 import surface collapses to one controlled boundary. It is the
port target of the TS ``bridge.ts`` (packages/protocol-ts/src/engine/
bridge.ts — already landed): each function here maps 1:1 onto a bridge
forward call the TS client makes via the protocol v1 envelope. Each
function lazily imports the underlying L3 module and forwards the call
unchanged, keeping boot light and preserving L3 module ownership.

TS rewrite reference: functions are grouped by domain (error bus /
memory / system / model / selector / injection / settings — see the
``# ── <domain> ──`` markers); the TS side reuses the same domain grouping
in ``bridge.ts`` and never re-implements the L3 authority behind them.
"""

from __future__ import annotations

from typing import Any


# ── error bus ──
def capture(*args: Any, **kwargs: Any) -> None:
    """Forward error capture to the L3 error bus."""
    from l3.error_bus import capture as _capture

    _capture(*args, **kwargs)


# ── memory domain ──
def memory_filter() -> Any:
    """Return the memory domain-filter instance."""
    from l3.memory.memory_domain_filter import get_memory_filter

    return get_memory_filter()


def export_corpus(limit: int = 0) -> dict:
    """Export the correction corpus."""
    from l3.memory.memory_record_source import export_corpus as _fn

    return _fn(limit=limit)


def digest_status() -> dict:
    """Return digest-cache switch status."""
    from l3.agent.digest_cache import digest_status as _fn

    return _fn()


def set_digest_switches(**kwargs: Any) -> dict:
    """Update digest-cache switches."""
    from l3.agent.digest_cache import set_digest_switches as _fn

    return _fn(**kwargs)


def tool_result_status() -> dict:
    """Return tool-result offload switch status."""
    from l3.agent.tool_result_cache import tool_result_status as _fn

    return _fn()


def set_tool_result_switches(**kwargs: Any) -> dict:
    """Update tool-result offload switches."""
    from l3.agent.tool_result_cache import set_tool_result_switches as _fn

    return _fn(**kwargs)


def compaction_status() -> dict:
    """Return hybrid extractor mode status."""
    from l3.memory.memory_extract import compaction_status as _fn

    return _fn()


def set_compaction_mode(mode: str) -> dict:
    """Set the hybrid extractor mode."""
    from l3.memory.memory_extract import set_compaction_mode as _fn

    return _fn(mode)


def premise_guard_status() -> dict:
    """Return premise-guard status."""
    from l3.memory.premise_guard import premise_guard_status as _fn

    return _fn()


def set_premise_guard(enabled: bool) -> dict:
    """Toggle the premise guard."""
    from l3.memory.premise_guard import set_premise_guard as _fn

    return _fn(enabled=enabled)


def inject_dedup_status() -> dict:
    """Return injection-content dedup status."""
    from l3.memory.memory_context import inject_dedup_status as _fn

    return _fn()


def set_inject_dedup(enabled: bool) -> dict:
    """Toggle injection-content dedup."""
    from l3.memory.memory_context import set_inject_dedup as _fn

    return _fn(enabled=enabled)


def audit_cell_context(cell_id: str = "") -> dict:
    """Audit per-agent context pressure."""
    from l3.agent.agent_loop import audit_cell_context as _fn

    return _fn(cell_id=cell_id)


def prompt_monitor_status() -> dict:
    """Return prompt bypass-monitor status."""
    from l3.agent.prompt_monitor import prompt_monitor_status as _fn

    return _fn()


def prompt_monitor_stats() -> dict:
    """Return prompt bypass-monitor stats."""
    from l3.agent.prompt_monitor import prompt_monitor_stats as _fn

    return _fn()


def set_prompt_monitor(enabled: bool, source: str = "shell") -> dict:
    """Toggle the prompt bypass monitor."""
    from l3.agent.prompt_monitor import set_prompt_monitor as _fn

    return _fn(enabled=enabled, source=source)


def emit_prompt_metrics() -> dict:
    """Emit prompt metrics now."""
    from l3.agent.prompt_monitor import emit_prompt_metrics as _fn

    return _fn()


def global_prompt_library_status() -> dict:
    """Return global prompt-library switch status."""
    from l3.agent.global_prompt_library import global_prompt_library_status as _fn

    return _fn()


def set_global_prompt_library_switches(enabled: bool) -> dict:
    """Update global prompt-library switches."""
    from l3.agent.global_prompt_library import set_global_prompt_library_switches as _fn

    return _fn(enabled=enabled)


def prompt_library_status() -> dict:
    """Return prompt-library switch status."""
    from l3.agent.prompt_library import prompt_library_status as _fn

    return _fn()


def set_prompt_library_switches(enabled: bool) -> dict:
    """Update prompt-library switches."""
    from l3.agent.prompt_library import set_prompt_library_switches as _fn

    return _fn(enabled=enabled)


def sensitive_status() -> dict:
    """Return sensitive-info switch status."""
    from l3.agent.sensitive_detect import sensitive_status as _fn

    return _fn()


def set_sensitive_switches(enabled: bool | None = None, action: str | None = None) -> dict:
    """Update sensitive-info switches."""
    from l3.agent.sensitive_detect import set_sensitive_switches as _fn

    return _fn(enabled=enabled, action=action)


def guard_status() -> dict:
    """Return recursion-guard status."""
    from l3.agent.compression_guard import guard_status as _fn

    return _fn()


def set_guard_switches(recursion_threshold: int | None = None, breaker_enabled: bool | None = None) -> dict:
    """Update recursion-guard switches."""
    from l3.agent.compression_guard import set_guard_switches as _fn

    return _fn(recursion_threshold=recursion_threshold, breaker_enabled=breaker_enabled)


def memory() -> Any:
    """Return the memory service instance."""
    from l3.memory.memory import get_memory

    return get_memory()


# ── system domain ──
def think_registry_stats() -> dict:
    """Return think-registry statistics (``/intents``)."""
    from l3.scheduler.think_registry import get_think_registry

    return get_think_registry().stats()


def scheduler_stats() -> dict:
    """Return scheduler statistics (``/scheduler``)."""
    from l3.scheduler.scheduler import get_scheduler

    s = get_scheduler()
    return s.stats() if hasattr(s, "stats") else {}


def obs_bus_summary() -> dict:
    """Return observability-bus summary (``/observe``)."""
    from l3.bus.observability_bus import get_obs_bus

    return get_obs_bus().summary()


def retriever_status() -> dict:
    """Return skill-retriever status."""
    from l3.memory.skill_retriever import retriever_status as _fn

    return _fn()


def set_retriever_backend(**kwargs: Any) -> dict:
    """Switch the skill-retriever backend."""
    from l3.memory.skill_retriever import set_backend as _fn

    return _fn(**kwargs)


def r4_evolve_skill(intent: str) -> dict:
    """Evolve an R4 agent skill from an intent."""
    from l3.memory.r4_agent import get_r4_agent

    return get_r4_agent().evolve_skill(intent)


def r4_register_custom_skill(**kwargs: Any) -> dict:
    """Register a custom skill on the R4 agent."""
    from l3.memory.r4_agent import get_r4_agent

    return get_r4_agent().register_custom_skill(**kwargs)


def link_skill_graph(sm: Any, name: str, scope: str, tags: list[str]) -> dict:
    """Link a registered skill into the skill graph."""
    from l3.memory.r4_skill_retrieval import link_registered_skill_graph

    return link_registered_skill_graph(sm, name, scope, tags)


def cell_cache_stats(cell_id: str) -> dict:
    """Return one cell's cache statistics."""
    from l3.cell import get_cell

    cell = get_cell(cell_id)
    return cell.cache.stats() if hasattr(cell, "cache") else {}


# ── model domain ──
def model_apply_strategy(scope: str, name: str) -> dict:
    """Apply a strategy pack on a model scope."""
    from l3.services.model_service import get_service

    return get_service().apply_strategy(scope, name)


def model_clear_strategy(scope: str) -> dict:
    """Clear the strategy pack on a model scope."""
    from l3.services.model_service import get_service

    return get_service().clear_strategy(scope)


def model_resolve(role: str) -> dict:
    """Resolve one role's provider/model as JSON data (no object leak)."""
    from l3.services.model_service import get_service

    cfg = get_service().resolve(role)
    return {"provider": cfg.provider, "model": cfg.model}


def model_providers() -> list[str]:
    """Return the registered provider names."""
    from l3.services.model_service import get_service

    return get_service().list_providers()


def think_clear_strategy(scope: str, name: str) -> dict:
    """Clear a peer think-strategy pack."""
    from l3.scheduler.think_registry import get_think_registry

    return get_think_registry().clear_strategy(scope, name)


def think_apply_strategy(scope: str, cell_id: str, pack: str) -> dict:
    """Apply a peer think-strategy pack."""
    from l3.scheduler.think_registry import get_think_registry

    return get_think_registry().apply_strategy(scope, cell_id, pack)


def settings_set(key: str, value: Any) -> dict:
    """Write one settings key through the settings center."""
    from l3.config.settings_center import get_center

    return get_center().set(key, value)


# ── selector / cell domain ──
def cell_ids() -> list[str]:
    """Return the registered cell ids."""
    from l3.cell import get_cells

    return list(get_cells().keys())


def cell_liveness(cell_id: str) -> dict:
    """Return one cell's liveness snapshot."""
    from l3.cell import get_cell

    return get_cell(cell_id).liveness()


def cell_agent_reachable(cell_id: str, agent_id: str) -> dict:
    """Ask one cell whether an agent is reachable."""
    from l3.cell import get_cell

    return get_cell(cell_id).agent_reachable(agent_id)


def cell_territory(cell_id: str) -> list[str]:
    """Return one cell's territory roots."""
    from l3.cell import get_cell

    return list(getattr(get_cell(cell_id), "territory", []) or [])


# ── injection guard domain ──
def injection_scan(message: str) -> float:
    """Scan a message for injection patterns; returns risk score 0.0-1.0."""
    from l3.services.injection_guard import injection_scan as _fn

    return _fn(message)


def injection_verify(message: str) -> dict:
    """Adjudicate one message through the injection guard."""
    from l3.services.injection_guard import injection_verify as _fn

    return _fn(message)


def set_llm_reviewer(callback: Any) -> None:
    """Register an external LLM reviewer for prompt injection."""
    from l3.services.injection_guard import set_llm_reviewer as _fn

    _fn(callback)


# ── card / plugin / cell / terminal domains ──
def card_registry() -> Any:
    """Return the card registry."""
    from l3.card.card_registry import get_registry

    return get_registry()


def plugin_center() -> Any:
    """Return the central plugin center."""
    from l3.services.central_plugin import get_center

    return get_center()


def cell(cell_id: str = "") -> Any:
    """Return one cell by id."""
    from l3.cell import get_cell

    return get_cell(cell_id)


def reset_cells() -> None:
    """Reset the cell registry (test/restart helper)."""
    from l3.cell import reset_cells as _fn

    _fn()


def terminals() -> Any:
    """Return the agent-terminal registry."""
    from l3.agent_terminal import get_terminals

    return get_terminals()


# ── settings / stats / security / resource domains ──
def settings_center() -> Any:
    """Return the settings center (config single write surface)."""
    from l3.config.settings_center import get_center

    return get_center()


def stats_center() -> Any:
    """Return the stats center."""
    from l3.services.stats_center import get_center

    return get_center()


def security_center() -> Any:
    """Return the central security center."""
    from l3.services.central_security import get_center

    return get_center()


def resource_manager() -> Any:
    """Return the resource-buffer manager."""
    from l3.resource_buffer.manager import get_manager

    return get_manager()


def memory_graph() -> Any:
    """Return the memory graph instance."""
    from l3.memory.memory_graph import get_graph

    return get_graph()


def think_registry() -> Any:
    """Return the think registry instance."""
    from l3.scheduler.think_registry import get_think_registry

    return get_think_registry()


# ── department / violation-monitor domain ──
def department_manager() -> Any:
    """Return the department manager."""
    from l3.cell.department import get_department_manager

    return get_department_manager()


def violation_monitor_status() -> dict:
    """Return violation-monitor status."""
    from l3.cell.violation_monitor import status as _fn

    return _fn()


def violation_monitor_set_enabled(enabled: bool) -> dict:
    """Enable or disable the violation monitor."""
    from l3.cell.violation_monitor import set_enabled as _fn

    return _fn(enabled)


def violation_monitor_reset() -> None:
    """Reset the violation monitor."""
    from l3.cell.violation_monitor import reset_violation_monitor as _fn

    _fn()


# ── coordinator / htn / l3a / tool-config domains ──
def coordinator() -> Any:
    """Return the central coordinator (L3A intent path)."""
    from l3.cell.peers.l3 import get_coordinator

    return get_coordinator()


def htn_a() -> Any:
    """Return the HTN planner instance."""
    from l3.bus.htn_a import get_htn_a

    return get_htn_a()


def cells() -> dict:
    """Return the cell registry keyed by id."""
    from l3.cell import get_cells

    return get_cells()


def llm_engine() -> Any:
    """Return the LLM engine adapter."""
    from l3.services.adapter_bridge import get_llm_engine

    return get_llm_engine()


def secretary() -> Any:
    """Return the L3A secretary instance."""
    from l3.cell.peers.l3a.secretary import get_secretary

    return get_secretary()


def reset_secretary() -> None:
    """Reset the L3A secretary."""
    from l3.cell.peers.l3a.secretary import reset_secretary as _fn

    _fn()


def tool_config() -> Any:
    """Return the tool-config class (completions/help metadata)."""
    from l3.tool_system.tool_config import ToolConfig

    return ToolConfig


# ── tool-system / harness / debug / auto-test domain ──
def harness_status() -> dict:
    """Return harness-mode status."""
    from l3.tool_system.harness import harness_status as _fn

    return _fn()


def reset_harness_mode() -> dict:
    """Reset the harness mode to its default."""
    from l3.tool_system.harness import reset_harness_mode as _fn

    return _fn()


def set_harness_mode(mode: str, confirmed: bool, source: str) -> dict:
    """Switch the harness mode (governed/code/semi/minimal)."""
    from l3.tool_system.harness import set_harness_mode as _fn

    return _fn(mode, confirmed=confirmed, source=source)


def engineering_debug() -> Any:
    """Return the engineering-debug manager."""
    from l3.tool_system.engineering_debug import get_engineering_debug

    return get_engineering_debug()


def input_activity() -> Any:
    """Return the input-activity monitor."""
    from l3.tool_system.input_activity import get_input_activity

    return get_input_activity()


def presentation_status() -> dict:
    """Return tool-presentation mode status."""
    from l3.tool_system.tool_presentation import presentation_status as _fn

    return _fn()


def reset_presentation_mode() -> dict:
    """Reset the tool-presentation mode."""
    from l3.tool_system.tool_presentation import reset_presentation_mode as _fn

    return _fn()


def set_presentation_mode(mode: str, source: str) -> dict:
    """Switch the tool-presentation mode (native/code/both)."""
    from l3.tool_system.tool_presentation import set_presentation_mode as _fn

    return _fn(mode, source=source)


def auto_test_status() -> dict:
    """Return AutoTestGate status."""
    from l3.tool_system.auto_test import auto_test_status as _fn

    return _fn()


def reset_auto_test() -> dict:
    """Reset the AutoTestGate mode."""
    from l3.tool_system.auto_test import reset_auto_test as _fn

    return _fn()


def set_auto_test(mode: str, source: str) -> dict:
    """Switch the AutoTestGate mode (off/async)."""
    from l3.tool_system.auto_test import set_auto_test as _fn

    return _fn(mode, source=source)


def list_tools() -> list:
    """Return the registered tool specs (metadata)."""
    from l3.tool_system.tool_spec import list_tools as _fn

    return _fn()


def get_tool(name: str) -> Any:
    """Return one tool spec by name (metadata lookup, never execution)."""
    from l3.tool_system.tool_spec import get_tool as _fn

    return _fn(name)


# ── l3a / session domain ──
def l3a_dispatch(args: list[str]) -> dict:
    """Route a command into the L3A daemon dispatch."""
    from l3.cell.peers.l3a import dispatch as _fn

    return _fn(args)


def l3a_start() -> None:
    """Start the L3A daemon (idempotent)."""
    from l3.cell.peers.l3a import start as _fn

    _fn()


def session_monitor(enabled: bool | None = None) -> dict:
    """Return session-monitor state, or toggle it when enabled is given."""
    from l3.agent_terminal import session_monitor as _state
    from l3.agent_terminal import session_monitor_status as _status
    from l3.agent_terminal import set_session_monitor as _set

    if enabled is None:
        return {"status": _status(), **_state()}
    return _set(enabled=enabled)


def auto_reload_session(agent_id: str, reason: str) -> dict:
    """Trigger a full session reload for one agent."""
    from l3.agent_terminal import auto_reload_session as _fn

    return _fn(agent_id, reason=reason)


def session_history_status() -> dict:
    """Return session-history switch state."""
    from l3.cell.peers.l3a.session_json import history_status as _fn

    return _fn()


def query_session_history(limit: int, session_id: str) -> dict:
    """Query session history records."""
    from l3.cell.peers.l3a.session_json import query_session_history as _fn

    return _fn(limit=limit, session_id=session_id)


def set_session_history(enabled: bool) -> dict:
    """Toggle session-history recording."""
    from l3.cell.peers.l3a.session_json import set_history as _fn

    return _fn(enabled=enabled)


def load_for_window(session_id: str, page: int, page_size: int) -> dict:
    """Load a conversation window via the dynamic session loader."""
    from l3.cell.peers.l3a.session_loader import load_for_window as _fn

    return _fn(session_id, page=page, page_size=page_size)


# ── terminal / scout domain ──
def scout_findings_display_limit() -> int:
    """Return the scout-findings display limit constant."""
    from l3.params import SCOUT_FINDINGS_DISPLAY_LIMIT

    return SCOUT_FINDINGS_DISPLAY_LIMIT


def scout_pool() -> Any:
    """Return the scout pool instance."""
    from l3.agent.scout import get_pool

    return get_pool()
