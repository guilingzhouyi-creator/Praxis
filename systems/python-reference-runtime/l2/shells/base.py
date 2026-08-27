"""Shell base — abstract dialect adapter over the shared L2 command engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .session import ShellSession


class Shell(ABC):
    """Abstract shell — a frontend dialect adapter over the L2 command engine.

    A shell translates frontend input lines into engine calls and returns
    render-ready dict results.  The engine contract (``l2.l2_shell``
    dispatch) stays stable while new frontends register additional shells.
    """

    name: ClassVar[str] = ""

    def create_session(self, session_id: str = "") -> ShellSession:
        """Create a fresh per-session state bound to this shell."""
        return ShellSession(shell=self.name, session_id=session_id)

    def get_session(self) -> ShellSession:
        """Return this shell's default session, creating it lazily.

        Shells may own a ``_session`` instance (e.g. ``TerminalShell``); the
        lazy fallback guarantees every shell has a stable session for legacy
        callers that read shell state without an explicit session argument.
        """
        session = getattr(self, "_session", None)
        if session is None:
            session = self.create_session()
            self._session = session
        return session

    def reset_session(self) -> ShellSession:
        """Replace this shell's default session with a fresh one."""
        self._session = self.create_session()
        return self._session

    @abstractmethod
    def run(self, text: str, session: ShellSession | None = None) -> dict:
        """Execute one line of input through the shell dialect; return a dict result."""
