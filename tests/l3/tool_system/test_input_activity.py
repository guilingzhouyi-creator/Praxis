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
