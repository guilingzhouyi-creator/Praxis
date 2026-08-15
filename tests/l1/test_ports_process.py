"""Tests for the ProcessPort exec seam (l1.kernel.ports.process)."""

from __future__ import annotations

import os

import pytest

from l1.kernel.params.kernel import (
    PROCESS_ERROR_EXECUTION,
    PROCESS_ERROR_NONE,
    PROCESS_ERROR_NOT_FOUND,
    PROCESS_RETURN_EXECUTION_ERROR,
)
from l1.kernel.ports import (
    ProcessOptions,
    ProcessPort,
    ProcessResult,
    SubprocessProcessPort,
    get_port,
    get_process_port,
    register_port,
    reset_ports,
)


class _FakeProcessPort(ProcessPort):
    """Deterministic process adapter used to verify resolver selection."""

    name = "test.process"

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def run(self, cmd: str, timeout: float = 0, options: ProcessOptions | None = None) -> ProcessResult:
        """Record a shell request and return a stable value result."""
        self.calls.append(("run", cmd))
        return ProcessResult(stdout="fake shell")

    def run_args(self, args: list[str], timeout: float = 0, options: ProcessOptions | None = None) -> ProcessResult:
        """Record an argument request and return a stable value result."""
        self.calls.append(("run_args", args))
        return ProcessResult(stdout="fake args")


@pytest.fixture
def port() -> SubprocessProcessPort:
    return SubprocessProcessPort()


def test_is_process_port(port: SubprocessProcessPort) -> None:
    assert isinstance(port, ProcessPort)
    assert port.name == "subprocess.process"


def test_run_echo_success(port: SubprocessProcessPort) -> None:
    r = port.run("echo hi")
    assert isinstance(r, ProcessResult)
    assert r.returncode == 0
    assert r.stdout.strip() == "hi"
    assert r.ok is True
    assert r.timed_out is False


def test_run_nonzero_returncode(port: SubprocessProcessPort) -> None:
    r = port.run("exit 3")
    assert r.returncode == 3
    assert r.ok is False


def test_run_args_no_shell(port: SubprocessProcessPort) -> None:
    r = port.run_args(["echo", "world"])
    assert r.returncode == 0
    assert "world" in r.stdout


def test_run_timeout_returns_timed_out(port: SubprocessProcessPort) -> None:
    r = port.run("sleep 5", timeout=0.3)
    assert r.timed_out is True
    assert r.ok is False


def test_run_args_nonexistent_binary_returns_failed_result(port: SubprocessProcessPort) -> None:
    # Non-timeout failure must translate into a failed ProcessResult, never
    # leak FileNotFoundError across the port boundary.
    r = port.run_args(["praxis-no-such-binary-xyz"])
    assert isinstance(r, ProcessResult)
    assert r.returncode == PROCESS_RETURN_EXECUTION_ERROR
    assert r.ok is False
    assert r.timed_out is False
    assert r.error_kind == PROCESS_ERROR_NOT_FOUND
    assert "no such" in r.stderr.lower() or "not found" in r.stderr.lower() or r.stderr != ""


def test_run_broken_shell_returns_failed_result(port: SubprocessProcessPort) -> None:
    # A shell path that cannot start raises OSError — translate, don't leak.
    r = port.run("echo hi", options=ProcessOptions(executable="/nonexistent/shell"))
    assert isinstance(r, ProcessResult)
    assert r.returncode == PROCESS_RETURN_EXECUTION_ERROR
    assert r.ok is False
    assert r.error_kind == PROCESS_ERROR_NOT_FOUND


def test_explicit_options_map_to_platform_helper(monkeypatch: pytest.MonkeyPatch, port: SubprocessProcessPort) -> None:
    """Map every FFI-safe option to the underlying bounded process helper."""
    import subprocess

    import l1.kernel.platform as platform

    captured: dict[str, object] = {}

    def _capture(args: list[str], timeout: float, **kwargs: object) -> subprocess.CompletedProcess:
        captured["args"] = args
        captured["timeout"] = timeout
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(platform, "run_args", _capture)
    options = ProcessOptions(
        cwd="/tmp",
        input_text="formatted input",
        env={"PROCESS_PORT_TEST": "1"},
        executable="/bin/echo",
    )
    result = port.run_args(["echo", "ignored"], timeout=4.0, options=options)

    assert result.ok is True
    assert captured == {
        "args": ["echo", "ignored"],
        "timeout": 4.0,
        "cwd": "/tmp",
        "input": "formatted input",
        "env": {"PROCESS_PORT_TEST": "1"},
        "executable": "/bin/echo",
    }


def test_run_args_invalid_cwd_returns_execution_error(port: SubprocessProcessPort) -> None:
    """Classify an invalid working directory as execution failure, not missing binary."""
    r = port.run_args(["echo", "ignored"], options=ProcessOptions(cwd="/praxis-invalid-cwd"))
    assert r.returncode == PROCESS_RETURN_EXECUTION_ERROR
    assert r.error_kind == PROCESS_ERROR_EXECUTION
    assert r.ok is False


def test_run_args_preserves_real_negative_child_returncode(
    monkeypatch: pytest.MonkeyPatch, port: SubprocessProcessPort
) -> None:
    """Keep a SIGINT-like child returncode distinct from adapter spawn failure."""
    import subprocess

    import l1.kernel.platform as platform

    monkeypatch.setattr(
        platform,
        "run_args",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode=PROCESS_RETURN_EXECUTION_ERROR),
    )
    result = port.run_args(["ignored"])
    assert result.returncode == PROCESS_RETURN_EXECUTION_ERROR
    assert result.error_kind == PROCESS_ERROR_NONE


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal return code only")
def test_run_args_preserves_posix_sigint_returncode(port: SubprocessProcessPort) -> None:
    """Keep a real SIGINT exit status separate from a missing executable."""
    result = port.run_args(["sh", "-c", "kill -INT $$"])
    assert result.returncode == PROCESS_RETURN_EXECUTION_ERROR
    assert result.error_kind == PROCESS_ERROR_NONE


def test_result_ok_property() -> None:
    assert ProcessResult(returncode=0).ok is True
    assert ProcessResult(returncode=1).ok is False
    assert ProcessResult(returncode=0, timed_out=True).ok is False
    assert ProcessResult(returncode=0, error_kind=PROCESS_ERROR_EXECUTION).ok is False


def test_resolvable_through_registry() -> None:
    reset_ports()
    register_port("process", SubprocessProcessPort())
    resolved = get_port("process")
    assert isinstance(resolved, ProcessPort)
    assert resolved.run("echo seam").stdout.strip() == "seam"
    reset_ports()


def test_get_process_port_uses_controlled_default_before_boot() -> None:
    """Resolve the stdlib adapter when boot has not registered a process port."""
    reset_ports()
    try:
        assert isinstance(get_process_port(), SubprocessProcessPort)
        assert get_process_port().run("echo preboot").stdout.strip() == "preboot"
    finally:
        reset_ports()


def test_get_process_port_prefers_registered_adapter() -> None:
    """Use the boot-registered adapter instead of the pre-boot fallback."""
    fake = _FakeProcessPort()
    reset_ports()
    try:
        register_port("process", fake)
        assert get_process_port() is fake
        assert get_process_port().run_args(["ignored"]).stdout == "fake args"
        assert fake.calls == [("run_args", ["ignored"])]
    finally:
        reset_ports()


def test_run_args_translates_unexpected_execution_error(
    monkeypatch: pytest.MonkeyPatch, port: SubprocessProcessPort
) -> None:
    """Return a value failure instead of leaking an adapter execution exception."""
    import l1.kernel.platform as platform

    def _raise(*args: object, **kwargs: object) -> None:
        raise ValueError("bad process input")

    monkeypatch.setattr(platform, "run_args", _raise)
    result = port.run_args(["echo", "ignored"])
    assert result.returncode == PROCESS_RETURN_EXECUTION_ERROR
    assert result.timed_out is False
    assert result.stderr == "bad process input"
    assert result.error_kind == PROCESS_ERROR_EXECUTION
