"""Process port abstraction — shell/command execution decoupled from the OS.

Rust-sink seam (roadmap `frontend-kernel-roadmap.md` §3–4 names `run_shell`
the primary Rust-migration candidate): callers that want the swappable path
resolve ``get_port("process")`` instead of importing ``platform.run_shell``
directly. The current runtime uses ``SubprocessProcessPort``, a thin adapter
over ``l1.kernel.platform`` — a future ``l1_kernel_rs`` registers its own
adapter with no change to callers.

The port returns ``ProcessResult`` (a plain value type) rather than a
``subprocess.CompletedProcess`` so no interpreter-specific object crosses the
boundary — mirroring the "no exception leak across port boundaries" contract
in ``ports/types.py``.
"""

from __future__ import annotations

import subprocess as _subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from l1.kernel.params.tool import TOOL_TERMINAL_TIMEOUT


def _to_text(value: str | bytes | None) -> str:
    """Normalize subprocess output (str/bytes/None) to text — never leaks bytes."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@dataclass
class ProcessResult:
    """Result of a process execution — FFI-clean, no CompletedProcess leak."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """Whether the process exited successfully (returncode 0, not timed out)."""
        return self.returncode == 0 and not self.timed_out


class ProcessPort(ABC):
    """Command/shell execution surface — decoupled from the host OS/interpreter."""

    name: str = "abstract.process"

    @abstractmethod
    def run(self, cmd: str, timeout: float = TOOL_TERMINAL_TIMEOUT, **kwargs: Any) -> ProcessResult:
        """Run *cmd* through the system shell; return a ProcessResult."""

    @abstractmethod
    def run_args(self, args: list[str], timeout: float = TOOL_TERMINAL_TIMEOUT, **kwargs: Any) -> ProcessResult:
        """Run a pre-split argument list (no shell); return a ProcessResult."""

    @abstractmethod
    def spawn_interactive(self, cwd: str = "") -> Any:
        """Spawn an interactive shell process handle (adapter-specific type)."""


class SubprocessProcessPort(ProcessPort):
    """Default adapter — delegates to ``l1.kernel.platform`` (stdlib subprocess).

    Wraps the existing cross-platform helpers so the shell-execution logic is
    not duplicated; only the CompletedProcess → ProcessResult conversion and
    the timeout-to-value translation live here.
    """

    name: str = "subprocess.process"

    def run(self, cmd: str, timeout: float = TOOL_TERMINAL_TIMEOUT, **kwargs: Any) -> ProcessResult:
        """Run *cmd* through the platform shell helper; translate failures to Results."""
        from l1.kernel.platform import run_shell

        try:
            cp = run_shell(cmd, timeout=timeout, **kwargs)
        except _subprocess.TimeoutExpired as e:
            return ProcessResult(returncode=-1, stdout=_to_text(e.stdout), stderr=_to_text(e.stderr), timed_out=True)
        except OSError as e:
            # e.g. FileNotFoundError for a broken shell — translate into a
            # failed ProcessResult so the "no exception leak across the port
            # boundary" contract holds for every failure, not just timeouts.
            return ProcessResult(returncode=-2, stderr=str(e), timed_out=False)
        return ProcessResult(returncode=cp.returncode, stdout=_to_text(cp.stdout), stderr=_to_text(cp.stderr))

    def run_args(self, args: list[str], timeout: float = TOOL_TERMINAL_TIMEOUT, **kwargs: Any) -> ProcessResult:
        """Run a pre-split argument list via the platform helper; translate failures."""
        from l1.kernel.platform import run_args as _run_args

        try:
            cp = _run_args(args, timeout=timeout, **kwargs)
        except _subprocess.TimeoutExpired as e:
            return ProcessResult(returncode=-1, stdout=_to_text(e.stdout), stderr=_to_text(e.stderr), timed_out=True)
        except OSError as e:
            # e.g. FileNotFoundError for a nonexistent binary — same contract
            # as run(): return a failed ProcessResult, never leak the exception.
            return ProcessResult(returncode=-2, stderr=str(e), timed_out=False)
        return ProcessResult(returncode=cp.returncode, stdout=_to_text(cp.stdout), stderr=_to_text(cp.stderr))

    def spawn_interactive(self, cwd: str = "") -> Any:
        """Spawn an interactive shell process in *cwd* via the platform helper."""
        from l1.kernel.platform import create_interactive_shell

        return create_interactive_shell(cwd=cwd)
