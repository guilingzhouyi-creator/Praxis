"""Process port abstraction — one-shot command execution decoupled from the OS.

Rust-sink seam (roadmap `frontend-kernel-roadmap.md` §3–4 names `run_shell`
the primary Rust-migration candidate): callers that want the swappable path
resolve ``get_process_port()`` instead of importing ``platform.run_shell``
directly. The resolver selects a boot-registered adapter, or a controlled
stdlib default before boot. The current runtime uses ``SubprocessProcessPort``,
a thin adapter over ``l1.kernel.platform`` — a future ``l1_kernel_rs``
registers its own adapter with no change to callers.

The port covers only bounded, non-interactive execution. Stateful ``Popen``
handles (terminal sessions, LSP stdio servers, and supervisors) remain Python3
runtime concerns: their pipes, callbacks, and lifecycle are deliberately not
part of this Rust-swappable contract.

The port returns ``ProcessResult`` (a plain value type) rather than a
``subprocess.CompletedProcess`` so no interpreter-specific object crosses the
boundary — mirroring the "no exception leak across port boundaries" contract
in ``ports/types.py``.
"""

from __future__ import annotations

import os
import subprocess as _subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import cast

from l1.kernel.params.kernel import (
    PROCESS_ERROR_EXECUTION,
    PROCESS_ERROR_NONE,
    PROCESS_ERROR_NOT_FOUND,
    PROCESS_RETURN_EXECUTION_ERROR,
    PROCESS_RETURN_TIMEOUT,
)
from l1.kernel.params.tool import TOOL_TERMINAL_TIMEOUT


def _to_text(value: str | bytes | None) -> str:
    """Normalize subprocess output (str/bytes/None) to text — never leaks bytes."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Result of a process execution — FFI-clean, no CompletedProcess leak."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error_kind: str = PROCESS_ERROR_NONE

    @property
    def ok(self) -> bool:
        """Whether the process exited successfully (returncode 0, not timed out)."""
        return self.returncode == 0 and not self.timed_out and not self.error_kind


@dataclass(frozen=True, slots=True)
class ProcessOptions:
    """Explicit, FFI-safe options for bounded process execution."""

    cwd: str | None = None
    input_text: str | None = None
    env: dict[str, str] | None = None
    executable: str | None = None


class ProcessPort(ABC):
    """One-shot command/shell execution surface decoupled from the host runtime."""

    name: str = "abstract.process"

    @abstractmethod
    def run(
        self, cmd: str, timeout: float = TOOL_TERMINAL_TIMEOUT, options: ProcessOptions | None = None
    ) -> ProcessResult:
        """Run *cmd* through the system shell; return a ProcessResult."""

    @abstractmethod
    def run_args(
        self, args: list[str], timeout: float = TOOL_TERMINAL_TIMEOUT, options: ProcessOptions | None = None
    ) -> ProcessResult:
        """Run a pre-split argument list (no shell); return a ProcessResult."""


class SubprocessProcessPort(ProcessPort):
    """Default adapter — delegates to ``l1.kernel.platform`` (stdlib subprocess).

    Wraps the existing cross-platform helpers so the shell-execution logic is
    not duplicated; only the CompletedProcess → ProcessResult conversion and
    the timeout-to-value translation live here.
    """

    name: str = "subprocess.process"

    def run(
        self, cmd: str, timeout: float = TOOL_TERMINAL_TIMEOUT, options: ProcessOptions | None = None
    ) -> ProcessResult:
        """Run *cmd* through the platform shell helper; translate failures to Results."""
        from l1.kernel.platform import run_shell

        try:
            cp = run_shell(cmd, timeout=timeout, **_option_kwargs(options))
        except _subprocess.TimeoutExpired as e:
            return ProcessResult(
                returncode=PROCESS_RETURN_TIMEOUT,
                stdout=_to_text(e.stdout),
                stderr=_to_text(e.stderr),
                timed_out=True,
            )
        except Exception as e:
            return _execution_failure(e, options)
        return ProcessResult(returncode=cp.returncode, stdout=_to_text(cp.stdout), stderr=_to_text(cp.stderr))

    def run_args(
        self, args: list[str], timeout: float = TOOL_TERMINAL_TIMEOUT, options: ProcessOptions | None = None
    ) -> ProcessResult:
        """Run a pre-split argument list via the platform helper; translate failures."""
        from l1.kernel.platform import run_args as _run_args

        try:
            cp = _run_args(args, timeout=timeout, **_option_kwargs(options))
        except _subprocess.TimeoutExpired as e:
            return ProcessResult(
                returncode=PROCESS_RETURN_TIMEOUT,
                stdout=_to_text(e.stdout),
                stderr=_to_text(e.stderr),
                timed_out=True,
            )
        except Exception as e:
            return _execution_failure(e, options)
        return ProcessResult(returncode=cp.returncode, stdout=_to_text(cp.stdout), stderr=_to_text(cp.stderr))


def _option_kwargs(options: ProcessOptions | None) -> dict[str, object]:
    """Translate the explicit port options into stdlib subprocess keywords."""
    if options is None:
        return {}
    kwargs: dict[str, object] = {}
    if options.cwd is not None:
        kwargs["cwd"] = options.cwd
    if options.input_text is not None:
        kwargs["input"] = options.input_text
    if options.env is not None:
        kwargs["env"] = options.env
    if options.executable is not None:
        kwargs["executable"] = options.executable
    return kwargs


def _execution_failure(error: Exception, options: ProcessOptions | None) -> ProcessResult:
    """Convert an adapter exception to a structured process value failure."""
    invalid_cwd = bool(options and options.cwd and not os.path.isdir(options.cwd))
    error_kind = (
        PROCESS_ERROR_NOT_FOUND if isinstance(error, FileNotFoundError) and not invalid_cwd else PROCESS_ERROR_EXECUTION
    )
    return ProcessResult(returncode=PROCESS_RETURN_EXECUTION_ERROR, stderr=str(error), error_kind=error_kind)


_DEFAULT_PROCESS_PORT = SubprocessProcessPort()


def get_process_port() -> ProcessPort:
    """Return the registered process adapter or the controlled pre-boot default.

    The fallback keeps L2/L3/L4 one-shot commands available during early boot
    and isolated tests. Once boot registers ``"process"``, every caller uses
    that adapter, including a foreign-language implementation.
    """
    from l1.kernel.ports.registry import get_port

    try:
        adapter = get_port("process")
    except KeyError:
        return _DEFAULT_PROCESS_PORT
    if not callable(getattr(adapter, "run", None)) or not callable(getattr(adapter, "run_args", None)):
        raise TypeError("process port must define run() and run_args()")
    return cast(ProcessPort, adapter)
