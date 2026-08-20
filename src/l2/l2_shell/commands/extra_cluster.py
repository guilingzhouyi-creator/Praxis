"""L2 Shell: cluster / cell / cross-cell / HTN commands.

Extracted from ``extra.py`` (per-domain split).  Owns the cluster-state,
default-cell, cross-cell-activity and HTN planner inspection commands.
"""

from __future__ import annotations

import logging

from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_cluster(args: list[str], session=None) -> dict:
    from l2.bridge import coordinator

    coord = coordinator()
    if not args:
        return {"success": True, "data": {"state": "single", "cells": []}}
    sub = args[0].lower()
    if sub == "status":
        cells: list[dict] = getattr(coord, "list_cells", lambda: [])()
        return {"success": True, "data": {"cells": cells}}
    return {"success": False, "error": _t("shell.app_error.usage_cluster")}


def _cmd_cells(args: list[str], session=None) -> dict:
    from l1.kernel.params.agent import DEFAULT_CELL_ID

    return {"success": True, "cell": DEFAULT_CELL_ID}


def _cmd_cross(args: list[str], session=None) -> dict:
    from l2.bridge import coordinator

    return {
        "success": True,
        "cross": coordinator().cross_cell_active if hasattr(coordinator(), "cross_cell_active") else False,
    }


def _cmd_htn(args: list[str], session=None) -> dict:
    if not args:
        return {"success": False, "error": _t("shell.app_error.usage_htn")}
    sub = args[0].lower()
    if sub == "a":
        from l2.bridge import htn_a

        planner = htn_a()
        return {"success": True, "methods": len(planner._methods) if hasattr(planner, "_methods") else 0}
    if sub == "status":
        return {"success": True}
    return {"success": False, "error": _t("shell.app_error.unknown_htn_subcommand")}
