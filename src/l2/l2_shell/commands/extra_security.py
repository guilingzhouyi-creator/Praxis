"""L2 Shell: central security commands.

Extracted from ``extra.py`` (per-domain split).  Owns the security
posture / audit inspection commands.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _cmd_security(args: list[str]) -> dict:
    from l3.services.central_security import get_center

    center = get_center()
    if args and args[0] == "audit":
        return {"success": True, "audit": center.audit_log() if hasattr(center, "audit_log") else []}
    return {"success": True, "status": "ok"}
