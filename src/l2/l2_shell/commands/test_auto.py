"""L2 Shell: AutoTestGate command (test_auto)."""

from __future__ import annotations

import logging

from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_test_auto(args: list[str], session=None) -> dict:
    """Show or switch the AutoTestGate mode (off / async)."""
    from l2.bridge import (
        auto_test_status,
        reset_auto_test,
        set_auto_test,
    )

    if not args:
        return {"success": True, **auto_test_status()}
    sub = args[0].lower()
    if sub == "reset":
        return {"success": True, **reset_auto_test()}
    if sub in ("off", "async"):
        return set_auto_test(sub, source="shell")
    return {"success": False, "error": _t("shell.app_error.unknown_auto_test_mode", sub=sub)}
