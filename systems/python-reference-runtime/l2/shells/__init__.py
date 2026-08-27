"""Shell family — per-shell session state, dialect base, and registry.

L2 owns a family of shells (dialect adapters over the shared L2 command
engine).  A shell translates frontend input lines into engine calls and
returns render-ready dict results; the engine contract (``l2.l2_shell``
dispatch) stays stable while new frontends register additional shells.
"""

from __future__ import annotations

from .base import Shell
from .family import ShellFamily, get_family, reset_family
from .session import ShellSession

__all__ = [
    "Shell",
    "ShellFamily",
    "ShellSession",
    "get_family",
    "reset_family",
]
