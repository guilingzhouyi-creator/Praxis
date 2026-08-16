"""System settings — kernel-side facade with dependency inversion.

Kernel callers read settings through this module; the authoritative
``Settings`` instance lives in ``l3.config.settings_adapter`` and is
**injected** at boot via ``set_settings_provider()`` (kernel never imports
L3). Before injection — standalone kernel use, L1-only tests — a pure
kernel fallback backed by ``DEFAULTS`` answers, so L1 never depends on an
upper layer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from l1.kernel.params.api import DEFAULT_MODEL_OLLAMA_CODER

# Re-export legacy DEFAULTS for callers that reference kernel.settings.DEFAULTS
DEFAULTS: dict[str, Any] = {
    "l1.kernel.allocator.tokens": 4096,
    "l1.kernel.allocator.ring1": 32,
    "l1.kernel.allocator.ring2": 200,
    "l1.kernel.swapper.interval": 30.0,
    "l1.kernel.syscall.audit_max": 5000,
    "cell.terminal.workers": 4,
    "cell.terminal.poll": 0.05,
    "cell.card.timeout": 30.0,
    "llm.provider": "ollama",
    "llm.model": DEFAULT_MODEL_OLLAMA_CODER,
    "llm.max_tokens": 2048,
    "llm.temperature": 0.3,
    "llm.rate_limit": 10,
    "device.rate_limit_default": 10,
    "device.health_check_interval": 60.0,
    "persistence.enabled": True,
    "persistence.interval": 30.0,
    "memory.graph.enabled": False,
    "memory.mer.enabled": False,
    "user_profile.enabled": False,
    # System-prompt injection switches (user-configurable via SettingsCenter API).
    # Each domain gates a block appended to agent system prompts; default True
    # keeps current behavior, set False to strip that injection globally.
    "prompt.inject.profile": True,
    "prompt.inject.constitution": True,
    "prompt.inject.skills": True,
    "prompt.inject.verification": True,
    "prompt.inject.memory": True,
    "prompt.inject.identity": True,
    # Department division (Phase 3) — when on, Cell count >= CELL_DEPARTMENT_MIN
    # triggers role specialization into departments (e.g. testing).
    "departments.enabled": False,
    # L3A-C secretary (Phase 4) — when on, the secretary records card
    # production contributions and upgrades assist → peer at the threshold.
    "l3a.secretary.enabled": True,
    # CI review (card-triggered automation) — mirrors praxis.yaml `ci:` section.
    "ci.review.enabled": True,
    "ci.review.auto_trigger": True,
    "ci.review.llm_review": False,
    "ci.review.escalate_reject": False,
    "ci.review.route_convention": False,
    "ci.review.reputation": False,
    "ci.review.lean_trace": False,
    "ci.review.todo_linkage": False,
    "ci.review.consume_auto_test_cache": True,
    "ci.review.notify.enabled": False,
    # CI review control-plane permissions (per-surface write gates; not
    # modifiable via the business surfaces themselves — config/admin only).
    "ci.control.api.writable": True,
    "ci.control.shell.writable": True,
    # Shell family (L2) — default dialect + master switch.  Members and
    # frontend bindings are declared in config/discovery/shells.yaml.
    "shells.enabled": True,
    "shells.default": "terminal",
    # Engineering debug mode (3.5) — marker-gated; ``auto`` is production
    # unless the configured marker file exists.
    "engineering_debug.mode": "auto",
    "engineering_debug.marker_file": ".praxis/debug_mode.flag",
    "engineering_debug.marker_required": True,
    "engineering_debug.verbose_logging": True,
    "engineering_debug.prompt_monitor": True,
    "engineering_debug.input.enabled": False,
    "engineering_debug.input.capture_content": False,
}


class _FallbackSettings:
    """Pure-kernel settings fallback backed by DEFAULTS (pre-injection / standalone).

    Implements the small read/write surface kernel callers use so L1 works
    without any injected provider; state is module-level so all readers
    within a process observe the same values.
    """

    def __init__(self, store: dict[str, Any]):
        self._store = store

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for a key, or the given default if absent."""
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> dict:
        """Write a setting and return the result dict."""
        self._store[key] = value
        return {"success": True, "key": key, "value": value}

    def set_many(self, pairs: dict[str, Any]) -> dict:
        """Write multiple settings and return the result dict."""
        self._store.update(pairs)
        return {"success": True, "updated": len(pairs)}

    def all(self) -> dict[str, Any]:
        """Return all settings as a flat key-value dict."""
        return dict(self._store)

    def category(self, prefix: str) -> dict[str, Any]:
        """Return all settings whose keys start with the given prefix."""
        return {k: v for k, v in self._store.items() if k.startswith(prefix)}

    def reset(self, key: str) -> dict:
        """Reset a setting back to its DEFAULTS value and return the result dict."""
        default = DEFAULTS.get(key)
        if default is None:
            self._store.pop(key, None)
        else:
            self._store[key] = default
        return {"success": True, "key": key}

    def reset_all(self) -> dict:
        """Reset all settings to their DEFAULTS values and return the result dict."""
        self._store.clear()
        self._store.update(DEFAULTS)
        return {"success": True}


# Module-level fallback store — shared by every _FallbackSettings view so
# concurrent L1 readers observe consistent values before injection.
_fallback_store: dict[str, Any] = dict(DEFAULTS)

# Injected at boot from L3 wiring (see boot_steps/config.py) — kernel never
# imports L3 directly. ``_settings_provider`` returns the authoritative
# Settings instance; ``_settings_resetter`` clears it (None when not wired).
_settings_provider: Callable[[], Any] | None = None
_settings_resetter: Callable[[], None] | None = None


def set_settings_provider(
    provider: Callable[[], Any],
    resetter: Callable[[], None] | None = None,
) -> None:
    """Register the authoritative settings accessor (called at boot from L3 wiring).

    Eliminates the ``from l3.config.settings_adapter import get_settings``
    import from the kernel layer — the provider is injected, not imported.
    """
    global _settings_provider, _settings_resetter
    _settings_provider = provider
    _settings_resetter = resetter


def inject_enabled(domain: str) -> bool:
    """Whether the ``prompt.inject.<domain>`` system-prompt injection is on.

    Best-effort: any settings failure falls back to enabled (True), so a
    broken settings path can never strip safety-critical context silently.
    """
    try:
        return bool(get_settings().get(f"prompt.inject.{domain}", True))
    except Exception:
        return True


def get_settings():
    """Get the global Settings instance (provider-backed; DEFAULTS fallback)."""
    if _settings_provider is not None:
        return _settings_provider()
    return _FallbackSettings(_fallback_store)


def reset_settings():
    """Reset the settings singleton (provider reset when wired; fallback otherwise)."""
    global _settings_provider, _settings_resetter
    if _settings_resetter is not None:
        from contextlib import suppress

        with suppress(Exception):
            _settings_resetter()
    _settings_provider = None
    _settings_resetter = None
    _fallback_store.clear()
    _fallback_store.update(DEFAULTS)
