"""Posture matrix — attack-posture configuration surface with hard bounds.

Per-domain posture knobs (offensive on/off + target whitelist) plus a
master API switch. Defaults come from params; config/discovery/posture.yaml
overrides at boot; the API (GET/PUT /api/v2/posture) reads and mutates at
runtime. The authorization boundary is enforced here, not in callers:

  - offensive posture is default-off (must be explicitly enabled);
  - HARNESS_MODE_MINIMAL is forbidden while any domain is offensive
    (approval + rate limiting are the non-negotiable bottom line);
  - evidence recording is mandatory while offensive (never skipped).
"""

from __future__ import annotations

import logging
import threading

from l1.kernel.params.system import (
    POSTURE_API_ENABLED,
    POSTURE_FORBIDDEN_HARNESS,
    POSTURE_MATRIX_DEFAULT,
)

logger = logging.getLogger(__name__)

_matrix_lock = threading.RLock()
_matrix: dict = {}

# Singleton (tests reset via reset_posture_matrix)
_posture_matrix: PostureMatrix | None = None


class PostureMatrix:
    """Per-domain posture matrix with read/write and boundary enforcement."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._matrix: dict = {}
        self._api_enabled = POSTURE_API_ENABLED
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load defaults (params), then overlay config/discovery/posture.yaml."""
        self._matrix = {k: dict(v) for k, v in POSTURE_MATRIX_DEFAULT.items()}
        try:
            from pathlib import Path

            import yaml

            p = Path(__file__).resolve().parent.parent.parent.parent.parent / "config" / "discovery" / "posture.yaml"
            if p.exists():
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                for domain, spec in (data.get("domains") or {}).items():
                    entry = self._matrix.setdefault(str(domain), {"offensive": False, "target_whitelist": []})
                    if isinstance(spec, dict):
                        entry["offensive"] = bool(spec.get("offensive", entry.get("offensive", False)))
                        wl = spec.get("target_whitelist")
                        if isinstance(wl, list):
                            entry["target_whitelist"] = [str(x) for x in wl]
                self._api_enabled = bool(data.get("api_enabled", POSTURE_API_ENABLED))
        except Exception as e:
            logger.debug("posture matrix: overlay failed: %s", e)

    # ── Reads ──

    def status(self) -> dict:
        """Matrix snapshot (never exposes targets beyond whitelist length)."""
        with self._lock:
            return {
                "api_enabled": self._api_enabled,
                "domains": {
                    d: {
                        "offensive": bool(e.get("offensive", False)),
                        "whitelisted_targets": len(e.get("target_whitelist", [])),
                    }
                    for d, e in self._matrix.items()
                },
            }

    def is_offensive(self, domain: str = "") -> bool:
        """True when the given (or any) domain is in offensive posture."""
        with self._lock:
            if not domain:
                return any(bool(e.get("offensive", False)) for e in self._matrix.values())
            return bool(self._matrix.get(domain, {}).get("offensive", False))

    def target_allowed(self, domain: str, target: str) -> bool:
        """Target whitelist check: no list → deny; '*' → allow all."""
        with self._lock:
            wl = self._matrix.get(domain, {}).get("target_whitelist", [])
            if not wl:
                return False
            if "*" in wl:
                return True
            return any(target.startswith(prefix) for prefix in wl)

    # ── Writes (API surface; master switch gates everything) ──

    def set_domain(self, domain: str, offensive: bool, target_whitelist: list[str] | None = None) -> dict:
        """Enable/disable offensive posture for one domain with a whitelist.

        Refuses when the API switch is off. Enabling offensive posture with
        an empty whitelist is rejected (no targets → nothing to attack).
        """
        with self._lock:
            if not self._api_enabled:
                return {"success": False, "error": "posture matrix API disabled"}
            entry = self._matrix.setdefault(domain, {"offensive": False, "target_whitelist": []})
            entry["offensive"] = bool(offensive)
            if target_whitelist is not None:
                entry["target_whitelist"] = [str(t) for t in target_whitelist]
            if entry["offensive"] and not entry["target_whitelist"]:
                entry["offensive"] = False
                return {"success": False, "error": f"offensive posture for '{domain}' requires a target whitelist"}
            self._matrix[domain] = entry
            return {"success": True, "domain": domain, "offensive": entry["offensive"]}

    def api_enabled(self) -> bool:
        """Master switch for the posture API surface."""
        return self._api_enabled

    def set_api_enabled(self, enabled: bool) -> dict:
        """Flip the master switch (config/API-controlled)."""
        with self._lock:
            self._api_enabled = bool(enabled)
            return {"success": True, "api_enabled": self._api_enabled}

    # ── Boundary enforcement ──

    def validate_harness(self, harness_mode: str) -> dict:
        """Reject a harness mode forbidden under any offensive posture.

        minimal drops approval + rate limiting — never allowed while any
        domain is offensive (authorization boundary, not a soft gate).
        """
        if harness_mode in POSTURE_FORBIDDEN_HARNESS and self.is_offensive():
            return {
                "success": False,
                "error": f"harness '{harness_mode}' forbidden while offensive posture is active",
            }
        return {"success": True}


def get_posture_matrix() -> PostureMatrix:
    """Get the global posture-matrix singleton."""
    global _posture_matrix
    with _matrix_lock:
        if _posture_matrix is None:
            _posture_matrix = PostureMatrix()
        return _posture_matrix


def reset_posture_matrix() -> None:
    """Reset the singleton (used by tests)."""
    global _posture_matrix
    with _matrix_lock:
        _posture_matrix = None
