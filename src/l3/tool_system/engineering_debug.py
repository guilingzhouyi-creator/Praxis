"""Marker-gated engineering debug mode and developer prompt controls."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from l1.kernel.params.system import (
    ENGINEERING_DEBUG_INPUT_ENABLED_DEFAULT,
    ENGINEERING_DEBUG_MARKER_FILE_DEFAULT,
    ENGINEERING_DEBUG_MARKER_RECHECK_INTERVAL,
    ENGINEERING_DEBUG_MARKER_REQUIRED_DEFAULT,
    ENGINEERING_DEBUG_MODE_DEFAULT,
    ENGINEERING_DEBUG_MODES,
    ENGINEERING_DEBUG_PROMPT_MAX_CHARS,
    ENGINEERING_DEBUG_PROMPT_MONITOR_DEFAULT,
    ENGINEERING_DEBUG_VERBOSE_LOGGING_DEFAULT,
)

logger = logging.getLogger(__name__)

ENGINEERING_MODE = "engineering"
PRODUCTION_MODE = "production"
_PROMPT_OVERRIDE_PREFIX = "engineering_debug.prompt_overrides."
_DEVELOPER_ROLES = frozenset({"developer", "l3", "reviewer", "deployer"})


def _coerce_bool(value: Any, default: bool) -> bool:
    """Coerce configuration values to bool without treating ``"false"`` as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default if value is None else bool(value)


class EngineeringDebugManager:
    """Resolve and control the marker-gated engineering debug state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_check = 0.0
        self._marker_present = False
        self._marker_path = ""
        self._effective_mode = PRODUCTION_MODE
        self._previous_root_level: int | None = None
        self._debug_logging = False
        self._prompt_overrides_loaded = False
        self._prompt_baseline: dict[str, str | None] = {}
        self._effects_signature: tuple[bool, bool, bool] | None = None

    def _settings(self):
        from l3.config.settings_center import get_center

        return get_center()

    def _setting(self, key: str, default: Any) -> Any:
        try:
            return self._settings().get(key, default)
        except Exception:
            return default

    def _requested_mode(self) -> str:
        raw = self._setting("engineering_debug.mode", ENGINEERING_DEBUG_MODE_DEFAULT)
        if isinstance(raw, bool):
            return "on" if raw else "off"
        mode = str(raw or ENGINEERING_DEBUG_MODE_DEFAULT).strip().lower()
        return mode if mode in ENGINEERING_DEBUG_MODES else ENGINEERING_DEBUG_MODE_DEFAULT

    def _project_root(self) -> Path:
        """Resolve the deployment root without depending on the current directory."""
        try:
            from l1.kernel.paths import get_paths

            config_root = Path(get_paths().config_templates_dir).expanduser()
            if not config_root.is_absolute():
                config_root = Path.cwd() / config_root
            return config_root.resolve().parent
        except Exception:
            return Path.cwd().resolve()

    def marker_path(self) -> Path:
        """Return the configured marker path, rooted at the deployment root."""
        raw = str(self._setting("engineering_debug.marker_file", ENGINEERING_DEBUG_MARKER_FILE_DEFAULT) or "").strip()
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self._project_root() / path
        return path.resolve()

    def _marker_is_present(self, path: Path) -> bool:
        """Return true only for a regular, non-symlink marker file."""
        try:
            return path.is_file() and not path.is_symlink()
        except OSError:
            return False

    def _effective_for(self, requested: str, marker_present: bool) -> str:
        """Apply the marker gate to a requested mode."""
        if requested == "off":
            return PRODUCTION_MODE
        required = _coerce_bool(
            self._setting("engineering_debug.marker_required", ENGINEERING_DEBUG_MARKER_REQUIRED_DEFAULT),
            ENGINEERING_DEBUG_MARKER_REQUIRED_DEFAULT,
        )
        if required and not marker_present:
            return PRODUCTION_MODE
        return ENGINEERING_MODE

    def _refresh(self, force: bool = False) -> None:
        """Refresh the cached marker state and apply transition side effects."""
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_check < ENGINEERING_DEBUG_MARKER_RECHECK_INTERVAL:
                return
            requested = self._requested_mode()
            path = self.marker_path()
            present = self._marker_is_present(path)
            effective = self._effective_for(requested, present)
            previous = self._effective_mode
            self._last_check = now
            self._marker_path = str(path)
            self._marker_present = present
            self._effective_mode = effective
        enabled = effective == ENGINEERING_MODE
        self._apply_effects(enabled)
        if enabled:
            self._load_prompt_overrides()
        else:
            self._restore_prompt_overrides()
        if previous != effective:
            self._emit_transition(previous, effective, requested, present, str(path))

    def _apply_effects(self, enabled: bool) -> None:
        """Apply debug-only observability switches without touching execution gates."""
        verbose = _coerce_bool(
            self._setting("engineering_debug.verbose_logging", ENGINEERING_DEBUG_VERBOSE_LOGGING_DEFAULT),
            ENGINEERING_DEBUG_VERBOSE_LOGGING_DEFAULT,
        )
        target_debug = enabled and verbose
        monitor_enabled = enabled and _coerce_bool(
            self._setting("engineering_debug.prompt_monitor", ENGINEERING_DEBUG_PROMPT_MONITOR_DEFAULT),
            ENGINEERING_DEBUG_PROMPT_MONITOR_DEFAULT,
        )
        input_configured = _coerce_bool(
            self._setting("engineering_debug.input.enabled", ENGINEERING_DEBUG_INPUT_ENABLED_DEFAULT),
            ENGINEERING_DEBUG_INPUT_ENABLED_DEFAULT,
        )
        signature = (target_debug, monitor_enabled, input_configured)
        with self._lock:
            if signature == self._effects_signature:
                return
            self._effects_signature = signature
            if target_debug and not self._debug_logging:
                root = logging.getLogger()
                self._previous_root_level = root.level
                root.setLevel(logging.DEBUG)
                self._debug_logging = True
            elif not target_debug and self._debug_logging:
                root = logging.getLogger()
                if self._previous_root_level is not None:
                    root.setLevel(self._previous_root_level)
                self._previous_root_level = None
                self._debug_logging = False
        try:
            from l3.agent.prompt_monitor import set_prompt_monitor

            set_prompt_monitor(enabled=monitor_enabled, source="engineering_debug", internal=True)
        except Exception as exc:
            logger.debug("engineering_debug: prompt monitor transition skipped: %s", exc)
        try:
            from l3.tool_system.input_activity import get_input_activity

            get_input_activity().sync_from_mode(enabled)
        except Exception as exc:
            logger.debug("engineering_debug: input activity transition skipped: %s", exc)

    def _emit_transition(self, previous: str, current: str, requested: str, marker: bool, path: str) -> None:
        """Publish a best-effort transition record to audit and metrics channels."""
        data = {
            "previous": previous,
            "current": current,
            "requested": requested,
            "marker_present": marker,
            "marker_path": path,
            "source": "engineering_debug",
        }
        try:
            from l1.kernel.event import get_bus

            get_bus().emit_event("engineering_debug_mode_changed", data=data, source="engineering_debug")
        except Exception:
            pass
        try:
            from l3.bus.reference_channel import get_rc

            get_rc().event("engineering_debug_mode_changed", data=data, source="engineering_debug")
        except Exception:
            pass
        try:
            from l3.services.stats_center import MetricPoint, get_center

            get_center().ingest(
                MetricPoint(
                    name="engineering_debug.mode.change",
                    value=1.0,
                    tags={"mode": current, "marker": str(marker).lower()},
                    timestamp=time.time(),
                    metric_type="counter",
                )
            )
        except Exception:
            pass

    def _load_prompt_overrides(self) -> None:
        """Apply persisted developer prompt overrides while engineering mode is active."""
        with self._lock:
            if self._prompt_overrides_loaded:
                return
        try:
            from l1.kernel.prompts import get_prompt_override, set_prompt_override

            values = self._settings().all()
            for key, text in values.items():
                if key.startswith(_PROMPT_OVERRIDE_PREFIX) and isinstance(text, str):
                    prompt_key = key[len(_PROMPT_OVERRIDE_PREFIX) :]
                    with self._lock:
                        if prompt_key not in self._prompt_baseline:
                            self._prompt_baseline[prompt_key] = get_prompt_override(prompt_key)
                    set_prompt_override(prompt_key, text)
            with self._lock:
                self._prompt_overrides_loaded = True
        except Exception as exc:
            logger.debug("engineering_debug: prompt override restore skipped: %s", exc)

    def _restore_prompt_overrides(self) -> None:
        """Restore prompt values that were active before debug overlays were applied."""
        with self._lock:
            baseline = dict(self._prompt_baseline)
            self._prompt_baseline.clear()
            self._prompt_overrides_loaded = False
        if not baseline:
            return
        try:
            from l1.kernel.prompts import restore_prompt_override

            for prompt_key, text in baseline.items():
                restore_prompt_override(prompt_key, text)
        except Exception as exc:
            logger.debug("engineering_debug: prompt override restore skipped: %s", exc)

    def status(self) -> dict:
        """Return the resolved mode, marker state and linked observability state."""
        self._refresh()
        with self._lock:
            requested = self._requested_mode()
            marker = self._marker_present
            path = self._marker_path
            current = self._effective_mode
            debug_logging = self._debug_logging
        try:
            from l3.agent.prompt_monitor import prompt_monitor_status

            prompt_monitor = prompt_monitor_status()
        except Exception:
            prompt_monitor = {"enabled": False, "tracked_keys": 0}
        return {
            "success": True,
            "mode": current,
            "engineering": current == ENGINEERING_MODE,
            "requested_mode": requested,
            "marker_present": marker,
            "marker_path": path,
            "marker_required": _coerce_bool(
                self._setting("engineering_debug.marker_required", ENGINEERING_DEBUG_MARKER_REQUIRED_DEFAULT),
                ENGINEERING_DEBUG_MARKER_REQUIRED_DEFAULT,
            ),
            "logging": {"verbose": debug_logging, "level": "DEBUG" if debug_logging else "configured"},
            "prompt_monitor": prompt_monitor,
            "input_monitor": {
                "enabled": current == ENGINEERING_MODE
                and _coerce_bool(
                    self._setting("engineering_debug.input.enabled", ENGINEERING_DEBUG_INPUT_ENABLED_DEFAULT),
                    ENGINEERING_DEBUG_INPUT_ENABLED_DEFAULT,
                ),
                "capture_content": False,
            },
        }

    def refresh(self, *, force: bool = True) -> dict:
        """Refresh marker/config state and return the resulting status."""
        self._refresh(force=force)
        return self.status()

    def is_enabled(self) -> bool:
        """Return whether engineering debug mode is currently effective."""
        self._refresh()
        with self._lock:
            return self._effective_mode == ENGINEERING_MODE

    def _authorize(self, actor_id: str, role: str, ring: Any, source: str) -> dict | None:
        """Require an explicit developer role or ring-3 clearance for writes."""
        normalized = str(role or "").strip().lower()
        try:
            ring_value = int(ring)
        except (TypeError, ValueError):
            ring_value = 0
        if normalized not in _DEVELOPER_ROLES and ring_value < 3:
            return {
                "success": False,
                "error": "developer role or ring>=3 clearance required",
                "source": source,
                "actor_id": actor_id,
            }
        return None

    def set_mode(
        self,
        mode: str,
        *,
        actor_id: str = "",
        role: str = "",
        ring: Any = 0,
        source: str = "api",
    ) -> dict:
        """Set the requested mode, preserving the marker as the hard gate."""
        denied = self._authorize(actor_id, role, ring, source)
        if denied:
            return denied
        normalized = str(mode or "").strip().lower()
        if normalized not in ENGINEERING_DEBUG_MODES:
            return {"success": False, "error": f"mode must be one of {list(ENGINEERING_DEBUG_MODES)}"}
        self._refresh(force=True)
        if normalized == "on" and _coerce_bool(
            self._setting("engineering_debug.marker_required", ENGINEERING_DEBUG_MARKER_REQUIRED_DEFAULT),
            ENGINEERING_DEBUG_MARKER_REQUIRED_DEFAULT,
        ):
            with self._lock:
                present = self._marker_present
                path = self._marker_path
            if not present:
                return {
                    "success": False,
                    "error": "engineering debug marker is required before enabling mode",
                    "marker_path": path,
                }
        try:
            self._settings().set("engineering_debug.mode", normalized)
        except Exception as exc:
            return {"success": False, "error": f"failed to persist engineering debug mode: {exc}"}
        self._refresh(force=True)
        result = self.status()
        result["source"] = source
        result["actor_id"] = actor_id
        return result

    def reset_mode(self, *, actor_id: str = "", role: str = "", ring: Any = 0, source: str = "api") -> dict:
        """Remove the runtime mode override and return to deployment config."""
        denied = self._authorize(actor_id, role, ring, source)
        if denied:
            return denied
        try:
            self._settings().reset("engineering_debug.mode")
        except Exception as exc:
            return {"success": False, "error": f"failed to reset engineering debug mode: {exc}"}
        self._refresh(force=True)
        return self.status()

    def set_prompt_override(
        self,
        key: str,
        text: str,
        *,
        actor_id: str = "",
        role: str = "",
        ring: Any = 0,
        source: str = "api",
    ) -> dict:
        """Persist and apply one developer-only runtime prompt override."""
        denied = self._authorize(actor_id, role, ring, source)
        if denied:
            return denied
        self._refresh(force=True)
        if not self.is_enabled():
            return {"success": False, "error": "prompt overrides require engineering debug mode"}
        prompt_key = str(key or "").strip()
        prompt_text = str(text or "")
        if not prompt_key or "\n" in prompt_key or len(prompt_text) > ENGINEERING_DEBUG_PROMPT_MAX_CHARS:
            return {"success": False, "error": "invalid prompt key or prompt text exceeds configured limit"}
        try:
            from l1.kernel.prompts import set_prompt_override

            set_prompt_override(prompt_key, prompt_text)
            self._settings().set(f"{_PROMPT_OVERRIDE_PREFIX}{prompt_key}", prompt_text)
            return {"success": True, "key": prompt_key, "version": "updated", "source": source}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def prompt_status(self) -> dict:
        """Return prompt layers and version metadata for engineering inspection."""
        try:
            from l1.kernel.prompts import list_prompt_layers, prompt_versions

            return {"success": True, "layers": list_prompt_layers(), "versions": prompt_versions()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def rollback_prompt(
        self,
        key: str,
        version: int,
        *,
        actor_id: str = "",
        role: str = "",
        ring: Any = 0,
        source: str = "api",
    ) -> dict:
        """Rollback one prompt overlay and persist the restored text."""
        denied = self._authorize(actor_id, role, ring, source)
        if denied:
            return denied
        self._refresh(force=True)
        if not self.is_enabled():
            return {"success": False, "error": "prompt rollback requires engineering debug mode"}
        prompt_key = str(key or "").strip()
        try:
            from l1.kernel.prompts import get_prompt_override, rollback_prompt

            result = rollback_prompt(prompt_key, int(version))
            if result.get("success"):
                restored = get_prompt_override(prompt_key)
                self._settings().set(f"{_PROMPT_OVERRIDE_PREFIX}{prompt_key}", restored or "")
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}


_manager: EngineeringDebugManager | None = None
_manager_lock = threading.Lock()


def get_engineering_debug() -> EngineeringDebugManager:
    """Return the process-wide engineering debug manager."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = EngineeringDebugManager()
        return _manager


def engineering_debug_status() -> dict:
    """Return the effective engineering debug status."""
    return get_engineering_debug().status()


def reset_engineering_debug() -> None:
    """Reset the manager and restore production logging for tests/lifecycle."""
    global _manager
    if _manager is not None:
        _manager._restore_prompt_overrides()
        _manager._apply_effects(False)
    with _manager_lock:
        _manager = None
