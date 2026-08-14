"""Phase-1 wiring tests — the three consumer points actually hooked up:

B2  tool_pipeline preflight refuses a tool whose DVG prerequisites are
    unregistered (refuse-dispatch wiring).
B4  _init_skills_and_network registers the card→tool-stats bridge
    (completion listener live at boot).
B8  set_harness_mode rejects 'minimal' while offensive posture is active
    (authorization boundary wired into the harness switch).
"""

from __future__ import annotations

import pytest

from l3.tool_system.dvg import get_dvg, reset_dvg
from l3.tool_system.posture_matrix import get_posture_matrix, reset_posture_matrix


@pytest.fixture(autouse=True)
def _clean_state():
    reset_dvg()
    reset_posture_matrix()
    yield
    reset_dvg()
    reset_posture_matrix()


def test_b2_pipeline_preflight_refuses_unregistered_prereq():
    """A tool whose DVG prerequisite is missing is refused at preflight."""
    from l3.tool_system.tool_pipeline import ToolPipeline

    dvg = get_dvg()
    dvg.register_tool_deps("app_tool", ["missing_prereq"])

    pipe = ToolPipeline()
    blocked = pipe._preflight_checks(
        tool_name="app_tool",
        agent_id="agent-a",
        args={},
        domain="",
        nature="",
        _registry={"app_tool": object()},  # truthy so gate #1 passes → DVG gate runs
        _executor=None,
        _parent_call_id="",
        result={"steps": []},  # preflight appends gate steps
        spec=None,
        tool_ring_str="ring_1",
        token_budget=1000,
        _skip=set(),
        _start=0.0,
        call_id="c1",
    )
    assert blocked is not None
    assert "DVG" in blocked.get("error", "")


def test_b2_pipeline_preflight_passes_when_prereqs_registered():
    """With all prerequisites registered, the DVG check does not block."""
    from l3.tool_system.tool_pipeline import ToolPipeline

    dvg = get_dvg()
    dvg.register_tool_deps("app_tool", ["base_tool"])
    dvg.register_tool_deps("base_tool", [])

    pipe = ToolPipeline()
    blocked = pipe._preflight_checks(
        tool_name="app_tool",
        agent_id="agent-a",
        args={},
        domain="",
        nature="",
        _registry={"app_tool": object()},  # truthy so gate #1 passes
        _executor=None,
        _parent_call_id="",
        result={"steps": []},  # preflight appends gate steps
        spec=None,
        tool_ring_str="ring_1",
        token_budget=1000,
        _skip=set(),
        _start=0.0,
        call_id="c2",
    )
    # 1b passes; the next gate (clearance) blocks because no executor — but
    # the error must NOT be the DVG one, proving the wiring lets it through.
    assert blocked is not None
    assert "DVG" not in blocked.get("error", "")


def test_b4_boot_registers_card_tool_stats_bridge():
    """_init_skills_and_network wires the card→tool-stats bridge (idempotent)."""
    from l3.boot.boot_steps.runtime import _init_skills_and_network
    from l3.services.card_tool_stats import wire_card_tool_stats

    # Direct idempotent registration is the same path boot uses.
    r1 = wire_card_tool_stats()
    assert r1.get("success") is True
    r2 = wire_card_tool_stats()
    assert r2.get("registered") is True  # idempotent second call

    # The boot step itself runs without raising.
    result = _init_skills_and_network()
    assert "card_tool_stats" in result


def test_b8_harness_minimal_rejected_while_offensive():
    """set_harness_mode refuses 'minimal' once offensive posture is on."""
    from l3.tool_system.harness import reset_harness_mode, set_harness_mode

    pm = get_posture_matrix()
    pm.set_domain("attack", offensive=True, target_whitelist=["lab.local"])

    r = set_harness_mode("minimal", confirmed=True, source="test")
    assert r.get("success") is False
    assert "forbidden" in r.get("error", "")

    # governed stays allowed under offensive posture.
    r2 = set_harness_mode("governed", source="test")
    assert r2.get("success") is True
    reset_harness_mode()


def test_b8_harness_minimal_allowed_when_productive():
    """Without offensive posture, minimal still requires confirmation only."""
    from l3.tool_system.harness import reset_harness_mode, set_harness_mode

    r = set_harness_mode("minimal", confirmed=True, source="test")
    assert r.get("success") is True  # posture boundary not triggered
    reset_harness_mode()
