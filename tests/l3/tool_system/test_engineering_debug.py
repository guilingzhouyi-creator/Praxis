"""Engineering debug mode tests — marker gate, prompt writes and monitor policy."""

from __future__ import annotations

from l1.kernel.ports import reset_ports


def _configure_marker(tmp_path, present: bool):
    """Point the settings layer at an isolated marker file."""
    from l3.config.settings_center import get_center

    marker = tmp_path / "debug_mode.flag"
    if present:
        marker.write_text("enabled\n", encoding="utf-8")
    center = get_center()
    center.set_l2("engineering_debug.marker_file", str(marker))
    center.set_l2("engineering_debug.mode", "auto")
    return marker


def test_default_without_marker_is_production(tmp_path):
    """The default auto mode is production when the marker is absent."""
    _configure_marker(tmp_path, present=False)
    from l3.tool_system.engineering_debug import engineering_debug_status

    status = engineering_debug_status()
    assert status["mode"] == "production"
    assert status["engineering"] is False
    assert status["marker_present"] is False


def test_marker_enables_auto_mode(tmp_path):
    """The marker activates auto mode and the prompt monitor side-channel."""
    _configure_marker(tmp_path, present=True)
    from l3.tool_system.engineering_debug import engineering_debug_status

    status = engineering_debug_status()
    assert status["mode"] == "engineering"
    assert status["engineering"] is True
    assert status["prompt_monitor"]["enabled"] is True


def test_explicit_on_cannot_bypass_marker(tmp_path):
    """An explicit on request is denied when the marker is absent."""
    _configure_marker(tmp_path, present=False)
    from l3.tool_system.engineering_debug import get_engineering_debug

    result = get_engineering_debug().set_mode("on", role="developer", source="api")
    assert result["success"] is False
    assert "marker" in result["error"]


def test_mode_off_and_reset_restore_production(tmp_path):
    """Off is a fail-closed override and reset returns to marker-driven auto."""
    _configure_marker(tmp_path, present=True)
    from l3.tool_system.engineering_debug import get_engineering_debug

    manager = get_engineering_debug()
    assert manager.status()["engineering"] is True
    assert manager.set_mode("off", role="developer", source="api")["engineering"] is False
    assert manager.reset_mode(role="developer", source="api")["engineering"] is True


def test_prompt_override_requires_engineering_mode(tmp_path):
    """Prompt overlays are denied in production and versioned in engineering mode."""
    _configure_marker(tmp_path, present=False)
    from l3.tool_system.engineering_debug import get_engineering_debug

    manager = get_engineering_debug()
    denied = manager.set_prompt_override("global.performance", "custom", role="developer")
    assert denied["success"] is False
    assert "engineering debug" in denied["error"]

    _configure_marker(tmp_path, present=True)
    accepted = manager.set_prompt_override("global.performance", "custom", role="developer")
    assert accepted["success"] is True
    from l1.kernel.prompts import get_prompt

    assert get_prompt("global.performance") == "custom"


def test_api_prompt_monitor_cannot_enable_in_production(tmp_path):
    """The API-facing monitor switch respects the engineering mode gate."""
    _configure_marker(tmp_path, present=False)
    from l3.agent.prompt_monitor import set_prompt_monitor

    denied = set_prompt_monitor(enabled=True, source="api")
    assert denied["success"] is False
    _configure_marker(tmp_path, present=True)
    accepted = set_prompt_monitor(enabled=True, source="api")
    assert accepted["success"] is True


def test_prompt_overlay_is_marker_gated_and_restores_baseline(tmp_path):
    """Persisted debug overlays stay hidden in production and restore the baseline on exit."""
    from l1.kernel.prompts import clear_prompt_override, get_prompt, set_prompt_override
    from l3.config.settings_center import get_center
    from l3.tool_system.engineering_debug import get_engineering_debug

    prompt_key = "engineering.lifecycle.test"
    set_prompt_override(prompt_key, "deployment prompt")
    center = get_center()
    marker = _configure_marker(tmp_path, present=True)
    center.set(f"engineering_debug.prompt_overrides.{prompt_key}", "debug prompt")
    manager = get_engineering_debug()

    assert manager.status()["engineering"] is True
    assert get_prompt(prompt_key) == "debug prompt"
    center.set_l2("engineering_debug.mode", "off")
    assert manager.refresh()["engineering"] is False
    assert get_prompt(prompt_key) == "deployment prompt"
    assert marker.is_file()
    clear_prompt_override(prompt_key)


def test_production_does_not_load_persisted_prompt_overlay(tmp_path):
    """A persisted developer prompt is not exposed before the marker is present."""
    from l1.kernel.prompts import get_prompt
    from l3.config.settings_center import get_center
    from l3.tool_system.engineering_debug import get_engineering_debug

    prompt_key = "engineering.production.test"
    center = get_center()
    _configure_marker(tmp_path, present=False)
    center.set(f"engineering_debug.prompt_overrides.{prompt_key}", "hidden debug prompt")
    assert get_engineering_debug().status()["engineering"] is False
    assert get_prompt(prompt_key, "deployment fallback") == "deployment fallback"


def test_refresh_rechecks_marker_within_cache_window(tmp_path):
    """The public refresh hook bypasses the marker recheck cache for operators and tests."""
    from l3.config.settings_center import get_center
    from l3.tool_system.engineering_debug import get_engineering_debug

    marker = _configure_marker(tmp_path, present=False)
    manager = get_engineering_debug()
    assert manager.status()["engineering"] is False
    marker.write_text("enabled\n", encoding="utf-8")
    center = get_center()
    center.set_l2("engineering_debug.marker_file", str(marker))
    assert manager.refresh()["engineering"] is True


def test_ports_reset_is_available_for_new_input_boundary():
    """The shared port registry remains resettable after the new contract."""
    reset_ports()
