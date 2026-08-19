"""CacheStrategy — config-driven LLM prefix cache adaptation.

Behavior is driven by praxis.yaml → llm.cache section:

  llm:
    cache:
      defaults:
        optimize_prompt: true    # wrap in [System]/[Task]
        forward_user_id: false
        anthropic_format: false  # use top-level system field
        refresh_enabled: true    # runtime provider-probe refresh loop
      openai:
        optimize_prompt: true
        forward_user_id: true
      deepseek:
        optimize_prompt: true
        forward_user_id: true
      anthropic:
        optimize_prompt: false
        forward_user_id: true
        anthropic_format: true
      ollama:
        optimize_prompt: false

New providers can be added in YAML without any Python code change.
Plugins can still register custom strategies via register_strategy().
Runtime provider probes (``refresh_strategy``) refresh the per-provider
strategy idempotently from the capability keys in ``params/system.py``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from l1.kernel.params.system import (
    CACHE_CAP_PREFIX_CACHE,
    CACHE_CAP_STATEFUL,
    CACHE_CAP_USER_ID,
    CACHE_STRATEGY_REFRESH_ENABLED_DEFAULT,
)
from l1.kernel.ports import get_port as _get_port

logger = logging.getLogger(__name__)

# ── Global config (loaded from praxis.yaml at boot) ──

_cache_config: dict[str, dict] = {}


def load_cache_config(cfg: dict) -> None:
    """Load per-provider cache config from praxis.yaml → llm.cache."""
    global _cache_config
    if not cfg:
        return
    _cache_config.clear()
    _cache_config.update(cfg)
    # Ensure defaults exist
    if "defaults" not in _cache_config:
        _cache_config["defaults"] = {}
    d = _cache_config["defaults"]
    d.setdefault("optimize_prompt", True)
    d.setdefault("forward_user_id", False)
    d.setdefault("anthropic_format", False)
    d.setdefault("protocol", "stateful")
    d.setdefault("refresh_enabled", CACHE_STRATEGY_REFRESH_ENABLED_DEFAULT)
    # A config reload resets the probe fingerprint cache (fresh baseline).
    with _probe_lock:
        _probe_applied.clear()


# ── Pure capability→flag resolver (TS-equivalent portable) ──


def normalize_probe(probe: dict) -> dict:
    """Fold a provider probe into the CACHE_CAP_* capability vocabulary.

    Pure logic — TS-equivalent portable. A probe may carry explicit
    CACHE_CAP_* keys (params/system.py) or a ``supports`` set of capability
    strings (e.g. ``generate_with_messages`` / ``prefix_cache`` / ``user_id``);
    both are folded into a normalized dict with only the CACHE_CAP_* keys.
    """
    out = {
        key: bool(probe[key]) for key in (CACHE_CAP_PREFIX_CACHE, CACHE_CAP_STATEFUL, CACHE_CAP_USER_ID) if key in probe
    }
    supports = set(probe.get("supports") or ())
    if "prefix_cache" in supports:
        out.setdefault(CACHE_CAP_PREFIX_CACHE, True)
    if "generate_with_messages" in supports:
        out.setdefault(CACHE_CAP_STATEFUL, True)
    if "user_id" in supports:
        out.setdefault(CACHE_CAP_USER_ID, True)
    return out


def resolve_cache_flags(config: dict, probe: dict) -> dict:
    """Merge provider capability probe keys into cache strategy options.

    Pure logic — TS-equivalent portable: same input dicts yield the same
    output dict with no I/O or module state. Capability keys (CACHE_CAP_*)
    map onto the config flag vocabulary; an explicitly configured flag
    always wins over a probe hint; unknown probe keys are ignored.
    Returns a new dict without mutating *config*.
    """
    out = dict(config)
    for key, supported in normalize_probe(probe).items():
        if key == CACHE_CAP_STATEFUL and "protocol" not in config:
            out["protocol"] = "stateful" if supported else "stateless"
        elif key == CACHE_CAP_PREFIX_CACHE and "optimize_prompt" not in config:
            out["optimize_prompt"] = bool(supported)
        elif key == CACHE_CAP_USER_ID and "forward_user_id" not in config:
            out["forward_user_id"] = bool(supported)
    return out


# ── Runtime probe refresh (idempotent) ──

_probe_lock = threading.RLock()
_probe_applied: dict[str, str] = {}


def _probe_refresh_enabled() -> bool:
    """Return the runtime refresh master switch (defaults.on via params)."""
    defaults = _cache_config.get("defaults", {})
    raw = defaults.get("refresh_enabled", CACHE_STRATEGY_REFRESH_ENABLED_DEFAULT)
    return bool(raw)


def _probe_fingerprint(probe: dict) -> str:
    """Build a stable fingerprint from the known capability keys in a probe."""
    relevant = sorted((str(key), str(value)) for key, value in normalize_probe(probe).items())
    return "|".join(f"{k}={v}" for k, v in relevant)


def refresh_strategy(provider_name: str, probe: dict) -> dict:
    """Refresh a provider's strategy from a runtime capability probe.

    Idempotent: applies only when the probe's capability fingerprint
    differs from the last applied one, so repeated probes cause no churn.
    The master switch (llm.cache.defaults.refresh_enabled) gates the loop.

    Args:
        provider_name: provider key (e.g. 'openai', 'deepseek').
        probe: provider.probe() dict with CACHE_CAP_* capability keys.

    Returns:
        dict with success + applied/unchanged/disabled reason.
    """
    name = str(provider_name or "").strip().lower()
    if not name or not isinstance(probe, dict):
        return {"success": True, "applied": False, "reason": "empty provider or probe"}
    if not _probe_refresh_enabled():
        return {"success": True, "applied": False, "reason": "refresh disabled"}
    fingerprint = _probe_fingerprint(probe)
    if not fingerprint:
        return {"success": True, "applied": False, "reason": "probe has no capability keys"}
    with _probe_lock:
        if _probe_applied.get(name) == fingerprint:
            return {"success": True, "applied": False, "reason": "unchanged"}
        merged = resolve_cache_flags(dict(_cache_config.get(name, {})), probe)
        _cache_config[name] = merged
        _probe_applied[name] = fingerprint
    logger.info("cache_strategy: refreshed strategy for %s (%s)", name, fingerprint)
    return {"success": True, "applied": True, "provider": name, "opts": merged}


def reset_cache_strategy() -> None:
    """Reset the config + probe fingerprint cache (tests / lifecycle)."""
    with _probe_lock:
        _cache_config.clear()
        _probe_applied.clear()


# ── Config-driven strategy (covers all built-in providers) ──


class ConfigCacheStrategy:
    """Single strategy class driven by praxis.yaml → llm.cache config.

    Each provider's behavior is defined by three boolean flags:
      optimize_prompt  — wrap in [System]/[Task] sections
      forward_user_id  — pass user_id to provider for KV isolation
      anthropic_format — flag for Anthropic cache_control injection
    """

    def __init__(self, provider: str):
        self.provider = provider
        defaults = _cache_config.get("defaults", {})
        specific = _cache_config.get(provider, {})
        self._opts = {**defaults, **specific}

    @property
    def protocol(self) -> str:
        """Return the configured wire protocol (stateless | stateful | auto)."""
        return str(self._opts.get("protocol", "stateful"))

    def optimize(self, prompt: str, system: str, user_id: str = "") -> tuple[str, str, dict[str, Any]]:
        """Optimize prompt/system per provider flags; return updated prompt, system, and extra options."""
        extra: dict[str, Any] = {}
        if self._opts.get("forward_user_id", False) and user_id:
            extra["user_id"] = user_id
        if self._opts.get("anthropic_format", False):
            extra["_anthropic_format"] = True
        if self._opts.get("optimize_prompt", True):
            prompt, system = _get_port("llm").optimize_prompt(prompt, system)
        return prompt, system, extra


# ── Plugin strategy registry (for custom strategies) ──

_plugin_strategies: dict[str, Any] = {}


def register_strategy(provider_name: str, strategy: Any) -> None:
    """Register a custom cache strategy (for plugins with special needs)."""
    _plugin_strategies[provider_name.strip().lower()] = strategy


# ── Public API ──


def get_strategy(provider_name: str) -> ConfigCacheStrategy | Any:
    """Get cache strategy for a provider.

    Priority:
      1. Plugin-registered custom strategy
      2. Config-driven strategy (works for any provider in YAML)
    """
    name = provider_name.strip().lower()
    custom = _plugin_strategies.get(name)
    if custom:
        return custom
    return ConfigCacheStrategy(name)
