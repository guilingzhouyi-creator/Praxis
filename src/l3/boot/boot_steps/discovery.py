"""Boot step — params-derived config discovery registration.

Extracted from ``boot_steps.py``.  ``_init_discovery`` registers the
params-derived defaults (build/test detectors, ring gates, tool rates,
service timeouts, persistence, service limits, …) into the discovery
layer so ``get_config()`` consumers see them before YAML overrides merge.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _init_discovery() -> dict:
    """Auto-discover declarative YAML config snippets from config/discovery/.

    Merges them on top of params-derived defaults so later boot steps
    (load_config, load_tools, etc.) see the merged result.
    """
    from l1.kernel.discovery import (
        discover,
        register,
        register_discovery_dir,
    )
    from l1.kernel.params import agent as _pag
    from l1.kernel.params import api as _pa
    from l1.kernel.params import gatechain as _pgc
    from l1.kernel.params import kernel as _pk
    from l1.kernel.params import system as _ps
    from l1.kernel.params import tool as _pt

    # Register params-derived defaults for each config section
    register(
        "build_detectors",
        {
            "pip": {"cmd": ["python", "-m", "build"]},
            "cargo": {"cmd": ["cargo", "build"]},
            "npm": {"cmd": ["npm", "run", "build"]},
            "msbuild": {"cmd": ["msbuild"]},
            "dotnet": {"cmd": ["dotnet", "build"]},
        },
    )
    register(
        "test_detectors",
        {
            "pytest": {"cmd": ["python", "-m", "pytest"]},
            "cargo": {"cmd": ["cargo", "test"]},
            "npm": {"cmd": ["npm", "test"]},
            "dotnet": {"cmd": ["dotnet", "test"]},
            "vstest": {"cmd": ["vstest.console"]},
        },
    )
    register("provider_urls", dict(_pa.LLM_PROVIDER_URLS))
    # Ring → gate requirements (tool_spec.py reads get_config("ring_gates"))
    register(
        "ring_gates",
        {
            _pk.RING_1: ["G1", "G2"],
            _pk.RING_2_5: ["G1", "G2", "G3", "G4"],
            _pk.RING_3: ["G1", "G2", "G3", "G4", "G5"],
        },
    )
    # GateChain action-level danger ratings (gatechain.py reads this)
    register("gatechain_danger_levels", dict(_pgc.GATECHAIN_DANGER_LEVELS))
    # Constitution action sets (constitution.py reads get_config("constitution"))
    register(
        "constitution",
        {
            "file_actions": sorted(_pag.CONSTITUTION_FILE_ACTIONS),
            "modify_actions": sorted(_pag.CONSTITUTION_MODIFY_ACTIONS),
            "gate_actions": sorted(_pag.CONSTITUTION_GATE_ACTIONS),
            "scout_blocked": sorted(_pag.CONSTITUTION_SCOUT_BLOCKED),
        },
    )
    # Tool rate limiting (scheduler_rate.py reads get_config("tool_rates"))
    register(
        "tool_rates",
        {
            "ring_1": _pt.TOOL_RATE_RING_1,
            "ring_2_5": _pt.TOOL_RATE_RING_2_5,
            "ring_3": _pt.TOOL_RATE_RING_3,
        },
    )
    # Service timeouts (convention.py reads get_config("services"))
    register(
        "services",
        {
            "lsp_manager_timeout": _pa.LSP_MANAGER_TIMEOUT,
            "lsp_long_timeout": _pa.LSP_MANAGER_LONG_TIMEOUT,
            "lsp_diag_timeout": _pa.LSP_DIAG_TIMEOUT,
            "mcp_bridge_timeout": _pa.MCP_BRIDGE_TIMEOUT,
            "mcp_bridge_long_timeout": _pa.MCP_BRIDGE_LONG_TIMEOUT,
            "shell_session_timeout": _pa.SHELL_SESSION_TIMEOUT,
            "pool_queue_timeout": _pa.POOL_QUEUE_TIMEOUT,
            "term_handler_timeout": _pa.TERM_HANDLER_TIMEOUT,
            "term_handler_long_timeout": _pa.TERM_HANDLER_LONG_TIMEOUT,
            "gateway_queue_timeout": _pa.API_GATEWAY_QUEUE_TIMEOUT,
            "r4_agent_join_timeout": _pa.R4_AGENT_JOIN_TIMEOUT,
            "subagent_run_timeout": _pa.SUBAGENT_RUN_TIMEOUT,
            "subagent_join_timeout": _pa.SUBAGENT_JOIN_TIMEOUT,
            "convention_max_rounds": _pag.CONVENTION_MAX_ROUNDS,
            "convention_timeout": _pag.CONVENTION_TIMEOUT,
        },
    )

    # ── agent_configs.yaml sections (consumed only) ──
    register("skill_dirs", [".praxis/skills", "skills", ".skills"])
    register(
        "shell_aliases",
        {
            "rf": "read_file",
            "wf": "write_file",
            "ls": "list_directory",
            "g": "grep",
            "glob": "glob",
            "cat": "read_file",
            "h": "help",
            "q": "exit",
            "st": "status",
            "tl": "tools",
            "clr": "clear",
            "hist": "history",
        },
    )

    # Register tool timeout defaults (params → get_config fallback)
    # Covers every key consumed via get_tool_config() so praxis.yaml/discovery
    # overrides actually take effect instead of silently falling back.
    register(
        "tool",
        {
            "pip_install_timeout": _pt.TOOL_PIP_INSTALL_TIMEOUT,
            "npm_timeout": _pt.TOOL_NPM_TIMEOUT,
            "pyright_timeout": _pt.TOOL_PYRIGHT_TIMEOUT,
            "compile_check_timeout": _pt.TOOL_COMPILE_CHECK_TIMEOUT,
            "package_manager_timeout": _pt.TOOL_PACKAGE_MANAGER_TIMEOUT,
            "handler_timeout": _pt.TOOL_HANDLER_TIMEOUT,
            "web_timeout": _pt.TOOL_WEB_TIMEOUT,
            "search_timeout": _pt.TOOL_SEARCH_TIMEOUT,
            "terminal_timeout": _pt.TOOL_TERMINAL_TIMEOUT,
            "git_timeout": _pt.TOOL_GIT_TIMEOUT,
            "build_timeout": _pt.TOOL_BUILD_TIMEOUT,
            "grep_timeout": _pt.TOOL_GREP_TIMEOUT,
            "exec_timeout": _ps.SANDBOX_EXEC_TIMEOUT,
            "exec_token_budget": _pt.TOOL_EXEC_TOKEN_BUDGET,
            "harness_mode": _pt.HARNESS_MODE_DEFAULT,
            "loop.auto_test": _pt.AUTO_TEST_DEFAULT_MODE,
            "format_auto": _pt.TOOL_FORMAT_AUTO,
        },
    )

    # Register persistence defaults (params → get_config fallback)
    register(
        "persistence",
        {
            "interval": _ps.PERSIST_INTERVAL,
            "card_registry": _ps.CARD_REGISTRY_AUTO_SAVE,
            "card_gate": _ps.CARD_GATE_AUTO_SAVE,
            "pending_queue": _ps.PENDING_QUEUE_AUTO_SAVE,
            "issue_table": _ps.ISSUE_TABLE_AUTO_SAVE,
            "approval_gate": _ps.APPROVAL_GATE_AUTO_SAVE,
            "sandbox_state": _ps.SANDBOX_STATE_AUTO_SAVE,
            "todo_table": _ps.TODO_TABLE_AUTO_SAVE,
            "transaction_area": _ps.TRANSACTION_AREA_AUTO_SAVE,
            "statecharts": _ps.STATECHARTS_AUTO_SAVE,
            "execution_results": _ps.EXECUTION_RESULTS_AUTO_SAVE,
            "dialogue_session": _ps.DIALOGUE_SESSION_AUTO_SAVE,
        },
    )

    # Register service runtime limits (params → get_config fallback).
    # Declared declaratively in config/discovery/service_limits.yaml; consumers
    # read via get_config("service_limits", {}).get(key, params_default).
    register(
        "service_limits",
        {
            "execution_step_timeout": _ps.EXECUTION_STEP_TIMEOUT,
            "dialogue_max_turns": _ps.DIALOGUE_MAX_TURNS,
            "dialogue_max_context_tokens": _ps.DIALOGUE_MAX_CONTEXT_TOKENS,
            "dialogue_persist_every": _ps.DIALOGUE_PERSIST_EVERY,
            "transaction_area_max_queue": _ps.TRANSACTION_AREA_MAX_QUEUE,
            "monitor_bus_max_queued": _ps.MONITOR_BUS_MAX_QUEUED,
            "error_bus_query_limit": _ps.ERROR_BUS_QUERY_LIMIT,
            "record_center_default_limit": _ps.RECORD_CENTER_DEFAULT_LIMIT,
            "record_center_retention_days": _ps.RECORD_CENTER_RETENTION_DAYS,
            "memory_ring_score_char_weight": _ps.MEMORY_RING_SCORE_CHAR_WEIGHT,
            "memory_ring_score_tag_weight": _ps.MEMORY_RING_SCORE_TAG_WEIGHT,
            "memory_ring_score_high_importance": _ps.MEMORY_RING_SCORE_HIGH_IMPORTANCE,
            "memory_ring_score_moderate_importance": _ps.MEMORY_RING_SCORE_MODERATE_IMPORTANCE,
            "memory_ring_score_long_tokens": _ps.MEMORY_RING_SCORE_LONG_TOKENS,
            "memory_ring_score_medium_tokens": _ps.MEMORY_RING_SCORE_MEDIUM_TOKENS,
            "memory_ring_score_good_threshold": _ps.MEMORY_RING_SCORE_GOOD_THRESHOLD,
            "memory_ring_score_average_threshold": _ps.MEMORY_RING_SCORE_AVERAGE_THRESHOLD,
            # ── L4 key modules (config-driven via get_service_limit) ──
            "channel_ring_capacity": _pa.CHANNEL_RING_CAPACITY,
            "api_middleware_timeout": _pa.API_MIDDLEWARE_TIMEOUT,
            "lsp_cache_ttl": _pa.LSP_CACHE_TTL,
            "search_cache_max": _ps.SEARCH_CACHE_MAX,
            "ops_console_interval": _ps.OPS_CONSOLE_INTERVAL,
            "memory_recall_page_limit": _ps.MEMORY_RECALL_PAGE_LIMIT,
        },
    )

    # Sections consumed outside ConfigDiscovery (owners read the YAML files
    # directly) — registered so discover() merges them without
    # unregistered-section warnings.
    register("departments", {})  # department.py reads departments.yaml directly
    register("diff_languages", {})  # diff_language.py reads diff_languages.yaml directly
    register("diff_dictionary", {})  # diff_dict.py reads the diff_dictionary section
    register("dvg", {})  # boot_steps/tools.py _load_dvg reads dvg.yaml directly
    register("identities", {})  # identity_roles.yaml (also loaded directly below)
    register("subagent_specs", {})  # subagent_spec.py reads subagent_specs.yaml directly
    # Shell family (boot_steps/shells.py reads get_config("shells")) —
    # params-derived defaults sourced from the settings registry so the
    # family master switch and default dialect are never hardcoded here.
    import l1.kernel.settings as _settings_mod

    register(
        "shells",
        {
            "enabled": bool(_settings_mod.DEFAULTS.get("shells.enabled", True)),
            "default": str(_settings_mod.DEFAULTS.get("shells.default", "")),
            "shells": {},
            "bindings": {},
        },
    )

    # Declarative surfaces without consumers yet — registered with params
    # defaults so discover() hosts them (consumable via get_config).
    register(
        "review",
        {
            "enabled": _ps.REVIEW_PIPELINE_ENABLED_DEFAULT,
            "autofix_enabled": _ps.REVIEW_AUTOFIX_ENABLED_DEFAULT,
            "max_small_change_lines": _ps.REVIEW_SMALL_CHANGE_MAX_LINES,
        },
    )
    register(
        "posture",
        {"api_enabled": True, "domains": {k: dict(v) for k, v in _ps.POSTURE_MATRIX_DEFAULT.items()}},
    )

    # Register discovery directory
    from pathlib import Path as _Path

    dd = _Path(__file__).resolve().parent.parent.parent.parent.parent / "config" / "discovery"
    register_discovery_dir(str(dd))

    # identity_roles.yaml: three-identity keyword overrides (config-driven,
    # never hardcoded). Registered so match_identity / consumers read the
    # overrides before the prompt-registry defaults.
    try:
        import yaml as _yaml

        roles_path = dd / "identity_roles.yaml"
        if roles_path.exists():
            roles_data = _yaml.safe_load(roles_path.read_text(encoding="utf-8")) or {}
            register("identity_roles", roles_data)
            logger.info("discovery: identity_roles overrides loaded (%d key(s))", len(roles_data))
    except Exception as e:
        logger.warning("discovery: identity_roles load skipped: %s", e)

    # Run discovery (scans YAML → merges on top of defaults)
    n = discover()
    logger.info("discovery: loaded %d config snippet(s) from %s", n, dd)
    return {"success": True, "loaded": n}
