"""_RESETS completeness guards — conftest singleton resets stay valid.

Protects the ``tests/conftest.py`` ``_RESETS`` contract:
  - every registered (module, reset_fn) entry resolves to a real function
  - the known leak-prone singleton modules never drop out of ``_RESETS``
  - every module-level singleton discovered by ``scripts/py/check_singletons.py``
    is either registered or explicitly exempted (KNOWN_GAPS backlog)

New module-level singletons are surfaced by ``scripts/py/check_singletons.py``
(the discovery tool): evaluate each hit and either add a reset function +
``_RESETS`` entry, or document why it is exempt. This test consumes the
scanner so a brand-new singleton fails CI until it is handled.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import tests.conftest as conftest

# Modules that have leaked cross-test state historically (i18n locale,
# SkillManager usage counters, skill retriever corpus, l2 i18n cache).
LEAK_PRONE_MODULES = {
    "l1.kernel.errors",
    "l1.kernel.skill",
    "l3.memory.skill_retriever",
    "l2.i18n",
}

# Scanner backlog: modules with a module-level singleton + getter that are
# NOT yet in _RESETS. Each entry must be judged — move it to _RESETS (with a
# reset function) or keep it exempt with a reason. A singleton module that is
# neither registered nor listed here fails the guard below.
KNOWN_GAPS = frozenset(
    {
        # L1 kernel
        "l1.kernel.allocator",
        "l1.kernel.bus",
        "l1.kernel.constitution",
        "l1.kernel.constitution_checks",
        "l1.kernel.device",
        "l1.kernel.ipc",
        "l1.kernel.lifecycle",
        "l1.kernel.net",
        "l1.kernel.os",
        "l1.kernel.process",
        "l1.kernel.registry",
        "l1.kernel.resource",
        "l1.kernel.swapper",
        "l1.kernel.tool_chain",
        # L2
        "l2.selector",
        "l2.shell_session",
        # L3 agents
        "l3.agent.ai",
        "l3.agent.pal_router",
        "l3.agent.stagnation",
        "l3.agent.subagent_framework",
        # L3 buses
        "l3.bus.comm_monitor",
        "l3.bus.htn_a",
        "l3.bus.htn_planner",
        "l3.bus.ipc",
        "l3.bus.l3b_bus",
        "l3.bus.log",
        "l3.bus.message_gate",
        "l3.bus.monitor_bus",
        "l3.bus.observability_bus",
        "l3.bus.reference_channel",
        "l3.bus.task_bus",
        # L3 cards
        "l3.card.card_gate",
        "l3.card.card_pool",
        "l3.card.decomposer",
        "l3.card.execution_engine",
        "l3.card.pending_queue",
        "l3.card.transaction_area",
        # L3 cells
        "l3.cell.components.cell_monitor",
        "l3.cell.peers.central_collector",
        "l3.cell.peers.l3",
        "l3.cell.peers.l3a.subagent",
        "l3.cell.peers.l3a.summaries",
        # L3 config / discussion / error bus
        "l3.config.config",
        "l3.config.settings_adapter",
        "l3.discussion.issue_orchestrator",
        "l3.discussion.report_service",
        "l3.error_bus.core",
        # L3 memory
        "l3.memory.cache_doc",
        "l3.memory.central_memory",
        "l3.memory.context",
        "l3.memory.pager",
        "l3.memory.pager_bridge",
        "l3.memory.result_store",
        "l3.resource_buffer.manager",
        # L3 scheduler
        "l3.scheduler.acb",
        "l3.scheduler.think_registry",
        # L3 services
        "l3.services.approval_policy",
        "l3.services.central_plugin",
        "l3.services.central_security",
        "l3.services.content_trust",
        "l3.services.counter",
        "l3.services.fault_tolerance",
        "l3.services.file_editor.engine",
        "l3.services.file_editor.patch",
        "l3.services.fs_adapter",
        "l3.services.hook",
        "l3.services.identity",
        "l3.services.model_service",
        "l3.services.model_strategy",
        "l3.services.package_manager",
        "l3.services.process",
        "l3.services.prompt_engine",
        "l3.services.record_center",
        "l3.services.service_manager",
        "l3.services.session_export",
        "l3.services.stats_center",
        "l3.services.template",
        "l3.services.vspace",
        # L4 bridge
        "l4.ci",
        "l4.cron_scheduler",
        "l4.llm.llm",
        "l4.llm.model_registry",
        "l4.mcp_bridge",
        "l4.notify",
        "l4.ops_console",
        "l4.rpc.server",
        "l4.sandbox.sandbox_manager",
        "l4.search.search_engine",
        "l4.supervisor",
        "l4.user_session",
        "l4.vault.auth",
    }
)


def _load_scanner():
    """Load scripts/py/check_singletons.py by path."""
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "py" / "check_singletons.py"
    spec = importlib.util.spec_from_file_location("check_singletons", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestResetsEntriesResolve:
    """Every _RESETS entry must resolve to a callable reset function."""

    def test_all_entries_resolve(self):
        failures = []
        for module_name, (func_name, _) in conftest._RESETS.items():
            try:
                mod = importlib.import_module(module_name)
            except ImportError as e:
                failures.append(f"{module_name}: import failed ({e})")
                continue
            fn = getattr(mod, func_name, None)
            if not callable(fn):
                failures.append(f"{module_name}.{func_name}: not callable")
        assert not failures, "broken _RESETS entries:\n" + "\n".join(failures)


class TestLeakProneModulesStayRegistered:
    """Known leak-prone singleton modules must never drop out of _RESETS."""

    def test_leak_prone_modules_covered(self):
        resets = set(conftest._RESETS)
        missing = LEAK_PRONE_MODULES - resets
        assert not missing, f"leak-prone modules missing from _RESETS: {sorted(missing)}"


class TestScannerBacklogGuard:
    """scan_singletons.py discoveries must be registered or explicitly exempt."""

    def test_new_singletons_registered_or_exempt(self):
        scanner = _load_scanner()
        data = scanner.scan()
        scanned = {mod for mod, _ in data["with_getter"]}
        unhandled = scanned - set(conftest._RESETS) - KNOWN_GAPS
        assert not unhandled, (
            "singletons without reset or exemption: "
            + ", ".join(sorted(unhandled))
            + ". Add a reset function + _RESETS entry, or extend KNOWN_GAPS"
            " with a documented reason."
        )
