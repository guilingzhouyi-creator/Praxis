"""ShellSession — per-shell interactive session state."""

from __future__ import annotations

import threading
import time
from collections import deque

from l1.kernel.params.agent import DEFAULT_CELL_ID
from l1.kernel.params.system import SHELL_HISTORY_MAX_LIMIT


class ShellSession:
    """Mutable per-session state for a shell — mode, cell, agent, session id.

    Replaces the legacy process-global ShellState singleton: every shell
    owns one or more sessions, so concurrent frontends never share mutable
    state.  The engine's ``dispatch()`` accepts a session for direct-mode
    routing; legacy callers fall back to the deprecated global singleton.

    TS rewrite reference: per-session state maps onto the protocol v1
    identity snapshot (SessionIdentity) the TS SessionView attaches to —
    the TS side holds no ShellSession; it reads identity + events through
    the bridge (attach/replay) and leaves mutation to the Python host.
    """

    def __init__(self, shell: str = "", session_id: str = "") -> None:
        self._lock = threading.Lock()
        self.shell: str = shell
        self.mode: str = "L3A"
        self.cell_id: str = DEFAULT_CELL_ID
        self.agent_id: str = ""
        self.session_id: str = session_id
        self._preconnect_cache: dict = {}
        self._history: deque[dict] = deque(maxlen=SHELL_HISTORY_MAX_LIMIT)

    def record(self, text: str, kind: str = "command") -> None:
        """Append one input line to the bounded session history."""
        with self._lock:
            self._history.append({"ts": time.time(), "text": text, "kind": kind})

    def history(self, limit: int) -> list[dict]:
        """Return the most recent history entries in chronological order."""
        with self._lock:
            return list(self._history)[-limit:]

    def is_direct(self) -> bool:
        """Check if the session is in Direct (connected-to-agent) mode."""
        with self._lock:
            return self.mode == "DIRECT" and bool(self.agent_id)

    def switch_to_direct(self, cell_id: str, agent_id: str, session_id: str = "") -> None:
        """Switch the session to Direct mode, targeting a specific Cell/Agent."""
        with self._lock:
            self.mode = "DIRECT"
            self.cell_id = cell_id
            self.agent_id = agent_id
            self.session_id = session_id

    def switch_to_l3a(self) -> None:
        """Return the session to L3A (default) mode — disconnect current agent."""
        with self._lock:
            self.mode = "L3A"
            self.agent_id = ""
            self.session_id = ""

    def as_dict(self) -> dict:
        """Return a snapshot of the session state as a plain dict."""
        with self._lock:
            return {
                "shell": self.shell,
                "mode": self.mode,
                "cell_id": self.cell_id,
                "agent_id": self.agent_id,
                "session_id": self.session_id,
            }
