"""Sensitive-information detection — bypass check for compressed content.

Runs alongside the compression/folding path (bypass, never on the main
flow): before a conversation span is folded or a digest written, the text
is scanned for sensitive patterns (API keys, bearer tokens, private keys,
IPv4/IPv6 literals). Hits are reported so the operator can redact or stop
the fold; the scan itself never mutates content (degrade to a no-op on
errors).

Operator switches (API ``/api/v2/memory/sensitive`` + L2 ``/memory
sensitive``):
  enabled — master switch (default ON — bypass detection is a baseline guard)

Degrades gracefully: disabled or unavailable → empty result, never raises.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from l1.kernel.params.system import SENSITIVE_DETECT_ENABLED_DEFAULT

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": SENSITIVE_DETECT_ENABLED_DEFAULT}
_hydrated = False
_lock = threading.RLock()

# Config-file driven operator switch (l1.kernel.settings → SettingsCenter).
_SWITCH_ENABLED = "l3a.sensitive.enabled"


def _hydrate() -> None:
    """Hydrate the switch cache from SettingsCenter (config-file driven)."""
    global _hydrated
    if _hydrated:
        return
    with _lock:
        if _hydrated:
            return
        try:
            from l1.kernel.settings import get_settings

            _state["enabled"] = bool(get_settings().get(_SWITCH_ENABLED, SENSITIVE_DETECT_ENABLED_DEFAULT))
        except Exception:
            logger.debug("sensitive_detect: settings hydrate skipped", exc_info=True)
        _hydrated = True


def _persist(enabled: bool | None = None) -> None:
    """Persist the switch override to SettingsCenter (best-effort)."""
    if enabled is None:
        return
    try:
        from l1.kernel.settings import get_settings

        get_settings().set(_SWITCH_ENABLED, bool(enabled))
    except Exception:
        logger.debug("sensitive_detect: settings persist skipped", exc_info=True)


# Sensitive-pattern table (best-effort heuristic — NOT a secret vault).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"\b(?:sk|pk|ghp|gho|AKIA)[-_A-Za-z0-9]{12,}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("ipv6", re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{1,4}\b")),
)


def sensitive_status() -> dict:
    """Return the sensitive-detection switch state."""
    _hydrate()
    with _lock:
        return {"enabled": bool(_state["enabled"])}


def set_sensitive_switches(enabled: bool | None = None) -> dict:
    """Set the sensitive-detection operator switch.

    Args:
        enabled: master switch (None = keep current).

    Returns:
        dict with success flag and the effective switch.
    """
    _hydrate()
    final_enabled = bool(enabled) if enabled is not None else None
    with _lock:
        if final_enabled is not None:
            _state["enabled"] = final_enabled
    _persist(enabled=final_enabled)
    return {"success": True, **sensitive_status()}


def reset_sensitive() -> None:
    """Reset the sensitive-detection switch (tests / lifecycle)."""
    global _hydrated
    with _lock:
        _state["enabled"] = SENSITIVE_DETECT_ENABLED_DEFAULT
        _hydrated = False
    try:
        from l1.kernel.settings import get_settings

        get_settings().reset(_SWITCH_ENABLED)
    except Exception:
        logger.debug("sensitive_detect: settings reset skipped", exc_info=True)


def scan_text(text: str) -> list[dict[str, str]]:
    """Scan text for sensitive patterns (bypass, read-only).

    Args:
        text: content to scan (a message span, digest, or summary).

    Returns:
        List of hits: ``{"kind": ..., "fragment": <truncated match>}``.
        Empty when disabled or nothing matched.
    """
    _hydrate()
    with _lock:
        enabled = bool(_state["enabled"])
    if not enabled or not text:
        return []
    hits: list[dict[str, str]] = []
    try:
        for kind, pattern in _PATTERNS:
            for m in pattern.finditer(str(text)):
                fragment = m.group(0)
                hits.append({"kind": kind, "fragment": fragment[:24] + ("…" if len(fragment) > 24 else "")})
                if len(hits) >= 16:  # bounded report
                    return hits
        return hits
    except Exception as e:  # pragma: no cover - defensive at the boundary
        logger.debug("sensitive_detect: scan skipped: %s", e)
        return []
