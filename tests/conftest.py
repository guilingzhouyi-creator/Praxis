"""pytest conftest — singleton reset between tests to avoid state pollution."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

# ── xdist worker isolation ──
# Each parallel worker gets its own skill dir so parallel runs never contend
# on shared skill files. PRAXIS_DATA_DIR/PRAXIS_CONFIG_DIR are deliberately
# NOT overridden — tests like test_paths.py assert the default data_dir
# (".praxis") / config_file ("config/praxis.yaml") semantics, and those
# defaults must stay intact under xdist.
if os.environ.get("PYTEST_XDIST_WORKER"):
    _iso_dir = tempfile.mkdtemp(prefix="praxis-test-worker-")
    os.environ.setdefault("PRAXIS_SKILL_DIR", _iso_dir)

# Modules with singleton _xxx = None pattern that can pollute across tests
_RESETS = {
    "l4.api.api_gateway": ("stop_api", None),
    "l4.ci_review": ("reset_service", None),
    "l3.card.approval_gate": ("reset_gate", None),
    "l3.card.card_registry": ("reset_registry", None),
    "l3.card.issue": ("reset_table", None),
    "l3.memory.memory": ("reset_memory", None),
    "l3.memory.memory_domain_filter": ("reset_memory_filter", None),
    "l3.memory.memory_refinery": ("reset_refinery", None),
    "l3.tool_system.dvg": ("reset_dvg", None),
    "l3.memory.memory_graph": ("reset_graph", None),
    "l3.memory.memory_mer": ("reset_mer", None),
    "l3.services.user_profile": ("reset_service", None),
    "l3.config.settings_center": ("reset_center", None),
    "l3.tool_system.tool_registry": ("clear_mutes", None),
    "l3.tool_system.auto_test": ("reset_auto_test", None),
    "l3.tool_system.harness": ("reset_harness_mode", None),
    "l3.tool_system.security_mode": ("reset_security_mode", None),
    "l3.tool_system.security_evidence": ("reset_evidence", None),
    "l3.tool_system.tool_pipeline": ("reset_pipeline", None),
    "l3.services.capability_store": ("reset_capability_store", None),
    "l3.memory.r4_agent": ("stop_r4_agent", None),
    "l3.agent.scout": ("reset_pool", None),
    "l3.scheduler.scheduler": ("reset_scheduler", None),
    "l3.scheduler.scheduler_time": ("reset_time_scheduler", None),
    "l3.scheduler.scheduler_rate": ("reset_rate_scheduler", None),
    "l3.scheduler.scheduler_scope": ("reset_scope_scheduler", None),
    "l3.agent_terminal": ("reset_terminals", None),
    "l3.cell": ("reset_cells", None),
    "l3.error_bus": ("reset_bus", None),
    "l1.kernel.event": ("reset_bus", None),
    "l1.kernel.process": ("reset_table", None),
    "l4.lsp.lsp_manager": ("reset_manager", None),
    "l1.kernel.reputation": ("reset_reputation", None),
    "l1.kernel.gatechain": ("reset_gatechain", None),
    "l1.kernel.notify": ("reset_notify", None),
    "l1.kernel.sync": ("reset_registry", None),
    "l1.kernel.vfs": ("reset_vfs", None),
    "l3.boot.boot": ("reset_boot_state", None),
    "l3.boot.boot_registry": ("reset_registry", None),
    "l1.kernel.settings": ("reset_settings", None),
    "l1.kernel.errors": ("reset_error_capture_handler", None),
    "l2.l2_shell.state": ("reset_state", None),
    "l2.shells.family": ("reset_family", None),
    "l3.cell.peers.l3a": ("reset_daemon", None),
    "l3.bus.htn_planner": ("reset_service", None),
    "l4.llm.llm": ("reset_engine", None),
    "l3.memory.skill_retriever": ("reset_retriever", None),
    "l1.kernel.skill": ("reset_skill_manager", None),
    "l1.kernel.identity_binding": ("reset_identity_binding_manager", None),
    "l3.tool_system.posture_matrix": ("reset_posture_matrix", None),
    "l3.memory.tiered_cache": ("reset_tiered_cache", None),
    "l3.services.review_pipeline": ("reset_review_pipeline", None),
    "l3.services.card_tool_stats": ("reset_card_tool_stats", None),
    "l4.sandbox.diff_persist": ("reset_diff_persist", None),
    "l4.sandbox.diff_language": ("reset_registry", None),
    "l3.cell.department": ("reset_department_manager", None),
    "l3.cell.peers.l3a.secretary": ("reset_secretary", None),
    "l3.cell.peers.l3a.daemon": ("reset_daemon", None),
    "l3.services.file_editor_engine": ("reset_engine", None),
    "l3.services.file_editor_patch": ("reset_patch_manager", None),
    "l2.i18n": ("reset_i18n", None),
}


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset known singletons before each test to prevent state pollution.

    Lazy per-module: only modules already imported (``sys.modules``) are
    reset — a module the test suite never touched has no singleton to
    clean, so we skip its import cost instead of force-importing all 27.
    """
    errors = []
    for module_name, (func_name, _) in _RESETS.items():
        if module_name not in sys.modules:
            continue  # never imported → no singleton to reset
        try:
            mod = sys.modules[module_name]
            fn = getattr(mod, func_name, None)
            if fn:
                fn()
        except Exception as e:
            errors.append(f"{module_name}.{func_name}: {e}")
    # i18n locale state: errors.py already occupies the per-module reset slot
    # with reset_error_capture_handler, so reset the locale explicitly here —
    # otherwise a test that calls set_locale("zh-CN") leaks into every later
    # locale-sensitive test (parallel CI breakage history).
    try:
        from l1.kernel.errors import reset_locale

        reset_locale()
    except Exception as e:
        errors.append(f"l1.kernel.errors.reset_locale: {e}")
    # Command registry: after reset, reload default command defs + L2 shell
    # handlers so `/help` etc. stay registered across the full test run.
    # Only reload when the commands package was actually imported — an
    # unconditional importlib.reload() re-imports the whole L2 command tree
    # (pulling L3 modules) on every test, adding ~5s of setup cost.
    if "l2.l2_shell.commands" in sys.modules or "l1.kernel.commands" in sys.modules:
        try:
            from l1.kernel.commands import get_registry, load_command_defs, reset_registry

            reset_registry()
            get_registry()
            load_command_defs()
            import importlib

            import l2.l2_shell.commands as _cmds_mod

            importlib.reload(_cmds_mod)
        except Exception as e:
            errors.append(f"commands.reload: {e}")
    if errors:
        import logging

        logging.getLogger(__name__).debug("singleton resets: %s", errors)
    # Re-inject the L3-backed settings provider after reset — kernel never
    # imports L3; this simulates the boot wiring (boot_steps/config.py) that
    # normally installs the provider. Only when settings was actually used,
    # so pure-L1 test modules never force-import the L3 config stack.
    if "l1.kernel.settings" in sys.modules:
        try:
            from l1.kernel.settings import set_settings_provider
            from l3.config.settings_adapter import get_settings as _sg
            from l3.config.settings_adapter import reset_settings as _sr

            set_settings_provider(_sg, _sr)
        except Exception as e:
            errors.append(f"settings.provider: {e}")


# ── Shared fixtures for Cell / IRQ / PMU tests ──


@pytest.fixture(autouse=True)
def _isolate_evolved_skill_dirs(tmp_path, monkeypatch):
    """Point evolved-skill writes at a per-test tmp dir (xdist-safe).

    R4 skill tests persist evolved SKILL.md files into the active evolve-scope
    dirs (repo ``skills/evolved`` + data-dir ``.praxis/skills/evolved``). Under
    xdist those dirs are shared across workers, so a test that cleans them
    (rmtree) can delete a directory another worker is mid-write into — the
    "No such file" failures seen on a fresh checkout. Isolating the write
    targets per test removes the shared-dir race and the residue problem at
    once: tmp_path auto-cleans, and assertions that read ``get_paths()``
    (test_r4_agent_evolve_integration.py) resolve the same instance.
    """
    from l1.kernel.paths import get_paths

    p = get_paths()
    monkeypatch.setattr(p, "skill_project_evolved_dir", str(tmp_path / "evolved-project"))
    monkeypatch.setattr(p, "skill_evolved_dir", str(tmp_path / "evolved-global"))
    os.makedirs(p.skill_project_evolved_dir, exist_ok=True)
    os.makedirs(p.skill_evolved_dir, exist_ok=True)
    yield


class _FakePmu:
    """Mock PMU for tests — tracks increment calls."""

    def __init__(self):
        self.counts = {}

    def increment(self, name: str, delta: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + delta


@pytest.fixture
def fake_pmu():
    """Shared FakePmu instance for use across component tests."""
    return _FakePmu()


@pytest.fixture
def irq_controller(fake_pmu):
    """Fresh InterruptController wired to fake_pmu."""
    from l3.cell.components.cell_interrupt import InterruptController

    return InterruptController(cell_id="test-cell", pmu=fake_pmu)


@pytest.fixture
def empty_cell():
    """Minimal Cell instance for component integration tests."""
    from l3.cell import Cell

    return Cell(cell_id="test-cell", territory=["."])


@pytest.fixture
def cell_with_agents(empty_cell):
    """Cell with reader + writer agents pre-registered."""
    empty_cell.add_agent("agent-reader", role="reader", territory=["src/", "docs/"], ring=1)
    empty_cell.add_agent("agent-writer", role="writer", territory=["src/"], ring=2)
    return empty_cell


@pytest.fixture
def memory_manager():
    """MemoryManager instance for cross-Cell memory tests."""
    from l3.memory.memory import get_memory

    mm = get_memory()
    yield mm
    try:
        from l3.memory.memory import reset_memory

        reset_memory()
    except Exception:
        pass


@pytest.fixture
def terminal():
    """AgentTerminal instance for agent dispatch tests."""
    from l3.agent_terminal import get_terminal

    return get_terminal("test-agent", role="reader", territory=["."])
