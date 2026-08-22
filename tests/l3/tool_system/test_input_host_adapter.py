"""P1.5/P1.6 slice tests — host input adapter states + transactional enable."""

from __future__ import annotations

import os

import pytest

from l3.tool_system.input_activity import (
    HostInputSource,
    InputActivityController,
    create_host_input_source,
)


class _FailingProvider:
    """Provider whose start() always fails (simulates unavailable device)."""

    def __init__(self):
        self.stops = 0

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        self.stops += 1

    def snapshot(self):
        from l1.kernel.ports import InputActivitySnapshot

        return InputActivitySnapshot(state="unavailable", keyboard_active=False, pointer_active=False)


class _FakeDebug:
    """Engineering-debug fake that authorizes every operator call."""

    def _authorize(self, actor_id, role, ring, source):  # noqa: ARG002 — signature mirror
        return None

    def is_enabled(self) -> bool:
        return True


class _FakeCenter:
    """Settings-center double capturing writes; reads return the last value."""

    def __init__(self):
        self.values: dict[str, bool] = {}

    def set(self, key, value):
        self.values[key] = bool(value)

    def get_bool(self, key, default=False):
        return self.values.get(key, default)


@pytest.fixture()
def controller(monkeypatch):
    """Controller with a failing provider + debug/settings doubles wired."""
    provider = _FailingProvider()
    ctl = InputActivityController(provider=provider)
    center = _FakeCenter()

    monkeypatch.setattr("l3.tool_system.engineering_debug.get_engineering_debug", lambda: _FakeDebug())
    monkeypatch.setattr("l3.config.settings_center.get_center", lambda: center)
    return ctl, provider, center


def test_host_source_deterministic_no_devices(tmp_path):
    src = create_host_input_source(device_glob=str(tmp_path / "none" / "event*"))
    assert src.start() is False
    assert src.unavailable_reason == "no-input-devices"
    assert src.active() is False
    assert src.last_activity() == 0.0


def test_host_source_permission_denied(monkeypatch, tmp_path):
    node = tmp_path / "event0"
    node.write_bytes(b"x")
    real_open = os.open

    def deny(path, flags, *a, **kw):
        if "event" in str(path):
            raise PermissionError(13, "denied")
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr("glob.glob", lambda pattern: [str(node)])
    # patch through the SAME module object input_activity uses (`import os`)
    monkeypatch.setattr(os, "open", deny)
    src = HostInputSource(device_glob=str(node))
    assert src.start() is False
    assert src.unavailable_reason == "permission-denied"


def test_transactional_enable_rolls_back(controller):
    """P1.6: failed provider start must not persist false enablement."""
    ctl, provider, center = controller
    r = ctl.set_enabled(True, actor_id="op", role="admin", ring=3)
    assert r["success"] is False
    assert r.get("rolled_back") is True
    st = ctl.status()
    assert st["enabled"] is False
    assert st["configured"] is False
    # settings never recorded the lie
    assert all(v is False for _, v in center.values.items())


def test_disable_path_still_closes_provider(controller):
    ctl, provider, _ = controller
    r = ctl.set_enabled(False, actor_id="op", role="admin", ring=3)
    assert r["success"] is True
    assert provider.stops >= 1 or ctl.status()["configured"] is False


def test_sync_from_mode_never_fake_enables(monkeypatch, controller):
    ctl, _, center = controller
    center.set("engineering_debug.input.enabled", True)  # configured ON
    ctl.sync_from_mode(debug_enabled=True)
    st = ctl.status()
    # provider cannot start -> enablement stays honestly False
    assert st["enabled"] is False
