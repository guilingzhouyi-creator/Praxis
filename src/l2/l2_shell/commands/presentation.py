"""L2 Shell: tool presentation mode command (presentation)."""

from __future__ import annotations

import logging

from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_presentation(args: list[str], session=None) -> dict:
    """Show or switch the tool presentation mode (native / code / both)."""
    from l2.bridge import (
        presentation_status,
        reset_presentation_mode,
        set_presentation_mode,
    )

    if not args:
        return {"success": True, **presentation_status()}
    sub = args[0].lower()
    if sub == "reset":
        return {"success": True, **reset_presentation_mode()}
    if sub in ("native", "code", "both"):
        return set_presentation_mode(sub, source="shell")
    return {"success": False, "error": _t("shell.app_error.usage_presentation")}
