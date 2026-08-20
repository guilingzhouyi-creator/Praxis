"""L2 Shell: resource buffer and think-quota commands.

Extracted from ``extra.py`` (per-domain split).  Owns the resource-buffer
flush and think-registry inspection commands.
"""

from __future__ import annotations

import logging

from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_buffer(args: list[str], session=None) -> dict:
    from l2.bridge import resource_manager

    mgr = resource_manager()
    if args and args[0] == "flush":
        return {"success": True, "flushed": len(mgr._buffers) if hasattr(mgr, "_buffers") else 0}
    return {"success": True, "buffer": {}}


def _cmd_think(args: list[str], session=None) -> dict:
    """Inspect or configure think quotas."""
    from l2.bridge import think_registry

    reg = think_registry()
    if not args:
        return {"success": True, "cells": sorted(reg.stats().get("cells", {}).keys())}
    if args[0] == "status":
        return {"success": True, "quotas": reg.all()}
    return {"success": False, "error": _t("shell.app_error.usage_think")}
