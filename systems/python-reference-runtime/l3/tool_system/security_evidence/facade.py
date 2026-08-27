"""Security evidence — module-level facade (singleton + entry helpers).

Extracted from ``security_evidence.py``: the process-wide collector
singleton, the best-effort ``record_evidence`` / ``record_from_metric``
bridges and the event-bus policy listener. Implementation stays in
``core.py`` (``SecurityEvidence``); this module only wires the shared
instance and the never-raising entry points.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any

from .models import DECISION_BYPASS, DECISION_CHANGE

logger = logging.getLogger(__name__)

_instance: Any = None
_instance_lock = threading.Lock()


def get_evidence():
    """Return the shared SecurityEvidence collector (singleton)."""
    from .core import SecurityEvidence

    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SecurityEvidence()
        return _instance


def reset_evidence() -> None:
    """Drop the singleton (tests; next get_evidence() rebuilds the window)."""
    global _instance
    with _instance_lock:
        _instance = None


def record_evidence(
    phase: str,
    gate: str = "",
    decision: str = "ALLOW",
    target: str = "",
    source: str = "",
    tags: dict[str, str] | None = None,
    raw: dict[str, Any] | None = None,
    chain_kind: str = "",
) -> str:
    """Best-effort evidence recording — never raises (bypass principle).

    An empty ``chain_kind`` follows the newest open posture chain (or ambient).
    """
    try:
        return get_evidence().record(
            phase=phase,
            gate=gate,
            decision=decision,
            target=target,
            source=source,
            tags=tags,
            raw=raw,
            chain_kind=chain_kind,
        )
    except Exception:
        logger.debug("security_evidence: record skipped", exc_info=True)
        return ""


def record_from_metric(name: str, value: float, tags: dict | None = None) -> None:
    """Best-effort metric-to-evidence bridge (used by the boot sink)."""
    with contextlib.suppress(Exception):
        get_evidence().record_from_metric(name, value, tags)


_listener_attached = False


def ensure_listener(force: bool = False) -> None:
    """Attach the event-bus listener for L1-originated security events.

    ``security_policy_change`` (emitted by the L1 SkillManager policy write)
    lands in the chain so a soft-bypass switch is observable even though the
    policy module lives in the kernel layer. Idempotent (``force=True``
    re-attaches after an event-bus reset — tests). Never breaks the bus.
    """
    global _listener_attached
    if _listener_attached and not force:
        return
    _listener_attached = True
    try:
        from l1.kernel.event import get_bus

        def _on_policy(signal) -> None:
            data = dict(signal.data or {})
            enabled = bool(data.get("enabled"))
            get_evidence().record(
                phase="policy",
                gate="offensive_policy",
                decision=DECISION_CHANGE if enabled else DECISION_BYPASS,
                target="offensive-policy",
                source=signal.sender or "policy",
                tags={"enabled": str(enabled).lower()},
                raw=data,
                chain_kind="policy-bypass" if not enabled else "ambient",
            )
            if not enabled:
                get_evidence().begin_chain("policy-bypass", source=signal.sender or "policy")

        get_bus().on_event("security_policy_change", _on_policy)
        logger.debug("security_evidence: policy-change listener attached")
    except Exception:
        pass
