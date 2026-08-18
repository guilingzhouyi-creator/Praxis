"""L2 Shell: canonical direct-intent and scout commands (/intent, /scout).

Standard entry points replacing the legacy terminal `!` dialect: the
shared implementations live in l2.shells.terminal (intent_direct /
scout_commission) so both the engine commands and the legacy prefix run
identical code.
"""

from __future__ import annotations

from typing import Any

from l2.i18n import t as _t
from l2.shells.terminal import intent_direct, scout_commission


def _session() -> Any:
    """Return the current shell session (family-backed state)."""
    from l2.l2_shell.state import get_state

    return get_state()


def _cmd_intent(args: list[str]) -> dict:
    """Route a direct intent: /intent <text>[@<cell>/<agent>]."""
    text = " ".join(args)
    if not text:
        return {"success": False, "error": _t("shell.app_error.usage_intent")}
    session = _session()
    agent_id = session.agent_id
    if "@" in text:
        intent, _, route = text.partition("@")
        parts = route.split("/")
        if len(parts) > 1:
            agent_id = parts[1]
    else:
        intent = text
    return intent_direct(intent, agent_id)


def _cmd_scout(args: list[str]) -> dict:
    """Commission a Scout: /scout <task>."""
    task = " ".join(args)
    session = _session()
    return scout_commission(task, session.agent_id, session.cell_id)
