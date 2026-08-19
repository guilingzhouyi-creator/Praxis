"""Input activity tests — aggregate-only fake provider behavior."""

from __future__ import annotations


def test_fake_provider_reports_activity_without_content(tmp_path):
    """The fake adapter exposes activity state but no raw input fields."""
    from l3.config.settings_center import get_center
    from l3.tool_system.engineering_debug import engineering_debug_status
    from l3.tool_system.input_activity import FakeInputActivityPort, get_input_activity

    marker = tmp_path / "debug_mode.flag"
    marker.write_text("enabled\n", encoding="utf-8")
    center = get_center()
    center.set_l2("engineering_debug.marker_file", str(marker))
    center.set_l2("engineering_debug.mode", "auto")
    assert engineering_debug_status()["engineering"] is True

    provider = FakeInputActivityPort()
    controller = get_input_activity()
    controller.set_provider(provider)
    enabled = controller.set_enabled(True, role="developer", source="api")
    assert enabled["success"] is True
    provider.record_activity("keyboard")
    snapshot = controller.status()["snapshot"]
    assert snapshot["state"] == "active"
    assert snapshot["keyboard_active"] is True
    assert "key" not in snapshot
    assert "coordinates" not in snapshot


def test_reset_input_activity_does_not_persist_a_runtime_write(tmp_path):
    """Lifecycle reset stops the provider without changing persisted settings."""
    from l3.config.settings_center import get_center
    from l3.tool_system.engineering_debug import engineering_debug_status
    from l3.tool_system.input_activity import FakeInputActivityPort, get_input_activity, reset_input_activity

    marker = tmp_path / "debug_mode.flag"
    marker.write_text("enabled\n", encoding="utf-8")
    center = get_center()
    center.set_l2("engineering_debug.marker_file", str(marker))
    center.set_l2("engineering_debug.mode", "auto")
    center.set_l2("engineering_debug.input.enabled", False)
    assert engineering_debug_status()["engineering"] is True
    controller = get_input_activity()
    controller.set_provider(FakeInputActivityPort())
    assert controller.set_enabled(True, role="developer")["success"] is True
    assert center.get_bool("engineering_debug.input.enabled") is True
    reset_input_activity()
    assert center.get_bool("engineering_debug.input.enabled") is True


def test_per_device_sources_plug_into_controller(tmp_path):
    """P2-2: keyboard/pointer InputSourcePorts fold into one aggregate."""
    from l3.config.settings_center import get_center
    from l3.tool_system.engineering_debug import engineering_debug_status
    from l3.tool_system.input_activity import FakeInputSource, get_input_activity, reset_input_activity

    marker = tmp_path / "debug_mode.flag"
    marker.write_text("enabled\n", encoding="utf-8")
    center = get_center()
    center.set_l2("engineering_debug.marker_file", str(marker))
    center.set_l2("engineering_debug.mode", "auto")
    center.set_l2("engineering_debug.input.enabled", True)
    assert engineering_debug_status()["engineering"] is True

    controller = get_input_activity()
    kb = FakeInputSource("keyboard")
    pt = FakeInputSource("pointer")
    controller.set_sources(kb, pt)
    assert controller.set_enabled(True, role="developer", source="api")["success"] is True

    kb.record_activity()
    snap = controller.status()["snapshot"]
    assert snap["state"] == "active"
    assert snap["keyboard_active"] is True
    assert snap["pointer_active"] is False

    pt.record_activity()
    snap = controller.status()["snapshot"]
    assert snap["pointer_active"] is True
    assert "key" not in snap and "coordinates" not in snap

    reset_input_activity()


def test_platform_source_stubs_unsupported_until_filled():
    """Keyboard/Mouse stubs report unsupported until the §8 hook lands."""
    from l3.tool_system.input_activity import KeyboardInputPort, MouseInputPort

    kb = KeyboardInputPort()
    mouse = MouseInputPort()
    assert kb.name == "keyboard"
    assert mouse.name == "pointer"
    assert kb.start() is False
    assert mouse.start() is False
    assert kb.active() is False
    assert mouse.active() is False
    assert kb.last_activity() == 0.0
