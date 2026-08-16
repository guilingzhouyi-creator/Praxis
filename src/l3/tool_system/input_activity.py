"""Privacy-preserving input activity controller with no-op and fake adapters."""

from __future__ import annotations

import threading
import time
from typing import Any

from l1.kernel.ports import InputActivityPort, InputActivitySnapshot


class NoopInputActivityPort(InputActivityPort):
    """Unavailable-platform adapter that never observes raw input."""

    def start(self) -> bool:
        """Report that no input provider is available."""
        return False

    def stop(self) -> None:
        """Keep the no-op adapter stopped."""

    def snapshot(self) -> InputActivitySnapshot:
        """Return an unavailable activity snapshot."""
        return InputActivitySnapshot(source="noop", permission="unavailable")


class FakeInputActivityPort(InputActivityPort):
    """Deterministic adapter for tests and platform integration probes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running = False
        self._last_activity = 0.0
        self._keyboard_active = False
        self._pointer_active = False

    def start(self) -> bool:
        """Start the fake provider."""
        with self._lock:
            self._running = True
        return True

    def stop(self) -> None:
        """Stop the fake provider and clear active flags."""
        with self._lock:
            self._running = False
            self._keyboard_active = False
            self._pointer_active = False

    def record_activity(self, kind: str = "keyboard") -> None:
        """Record aggregate activity without retaining key or pointer data."""
        with self._lock:
            if not self._running:
                return
            self._last_activity = time.time()
            self._keyboard_active = kind in ("keyboard", "both")
            self._pointer_active = kind in ("pointer", "mouse", "both")

    def snapshot(self) -> InputActivitySnapshot:
        """Return the current fake aggregate."""
        with self._lock:
            now = time.time()
            idle = max(0.0, now - self._last_activity) if self._last_activity else 0.0
            active = self._running and (self._keyboard_active or self._pointer_active)
            return InputActivitySnapshot(
                state="active" if active else ("idle" if self._running else "unknown"),
                keyboard_active=self._keyboard_active,
                pointer_active=self._pointer_active,
                last_activity_at=self._last_activity,
                idle_seconds=idle,
                source="fake",
                permission="granted",
            )


class InputActivityController:
    """Gate input activity observation behind engineering mode and consent."""

    def __init__(self, provider: InputActivityPort | None = None) -> None:
        self._lock = threading.RLock()
        self._provider = provider or NoopInputActivityPort()
        self._enabled = False

    def set_provider(self, provider: InputActivityPort) -> None:
        """Replace the provider, stopping the previous adapter first."""
        with self._lock:
            self._provider.stop()
            self._provider = provider
            self._enabled = False

    def status(self) -> dict:
        """Return effective enablement and the aggregate snapshot."""
        from l3.tool_system.engineering_debug import get_engineering_debug

        debug_enabled = get_engineering_debug().is_enabled()
        with self._lock:
            snapshot = self._provider.snapshot()
            return {
                "success": True,
                "enabled": bool(self._enabled and debug_enabled),
                "configured": self._enabled,
                "capture_content": False,
                "snapshot": snapshot.__dict__.copy(),
            }

    def sync_from_mode(self, debug_enabled: bool) -> None:
        """Start or stop the provider when the engineering mode changes."""
        try:
            from l3.config.settings_center import get_center

            configured = get_center().get_bool("engineering_debug.input.enabled", False)
        except Exception:
            configured = False
        desired = bool(debug_enabled and configured)
        with self._lock:
            if desired and not self._enabled:
                self._enabled = True
                self._provider.start()
            elif not desired and self._enabled:
                self._enabled = False
                self._provider.stop()

    def set_enabled(
        self,
        enabled: bool,
        *,
        actor_id: str = "",
        role: str = "",
        ring: Any = 0,
        source: str = "api",
    ) -> dict:
        """Enable or disable aggregate input activity after operator checks."""
        from l3.tool_system.engineering_debug import get_engineering_debug

        manager = get_engineering_debug()
        denied = manager._authorize(actor_id, role, ring, source)
        if denied:
            return denied
        if enabled and not manager.is_enabled():
            return {"success": False, "error": "input monitoring requires engineering debug mode"}
        with self._lock:
            self._enabled = bool(enabled)
            started = self._provider.start() if self._enabled else False
            if not self._enabled:
                self._provider.stop()
        try:
            from l3.config.settings_center import get_center

            get_center().set("engineering_debug.input.enabled", bool(enabled))
        except Exception:
            pass
        return {"success": True, "started": started, **self.status()}


_controller: InputActivityController | None = None
_controller_lock = threading.Lock()


def get_input_activity() -> InputActivityController:
    """Return the process-wide input activity controller."""
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = InputActivityController()
        return _controller


def reset_input_activity() -> None:
    """Stop and reset the input activity controller."""
    global _controller
    if _controller is not None:
        with _controller._lock:
            _controller._enabled = False
            _controller._provider.stop()
    with _controller_lock:
        _controller = None
