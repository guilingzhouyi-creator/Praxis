"""Shell state accessor — delegates to the ShellFamily default shell.

Legacy callers (L4 API handlers, L2 command handlers, completer) read the
"current" shell state through ``get_state()`` / ``reset_state()`` without
an explicit session argument.  The state itself lives on the family's
default shell (``l2.shells.session.ShellSession``); this module is a thin
accessor, NOT a separate process-global singleton — so there is exactly one
mutable session source and per-session ``ShellSession`` instances (shell
family) are the real owners.

TS rewrite reference: state reads map onto the TS SessionView snapshot —
the TS side never holds session state; it pulls identity + events through
the bridge (attach/replay) exactly like this accessor pulls the family
default shell's state.
"""

from __future__ import annotations

from typing import TypeAlias

from l2.shells.session import ShellSession

ShellState: TypeAlias = ShellSession

# Stable fallback used ONLY while the ShellFamily is empty (early boot /
# isolated tests).  Once a shell is registered, get_state() delegates to the
# family default shell's session — this is not a second state source.
_fallback_state = ShellSession(shell="legacy")


def get_state() -> ShellState:
    """Return the default shell's session (family-backed)."""
    try:
        from l2.shells.family import get_family

        return get_family().default().get_session()
    except Exception:
        # Family not booted (e.g. early boot / isolated tests): fall back to
        # the stable module-level session so legacy callers never crash and
        # state mutations stay visible across get_state() calls.
        return _fallback_state


def reset_state() -> None:
    """Reset the default shell's session to a fresh default."""
    global _fallback_state
    try:
        from l2.shells.family import get_family

        get_family().default().reset_session()
    except Exception:
        # Nothing registered yet — reset the fallback session.
        _fallback_state = ShellSession(shell="legacy")
