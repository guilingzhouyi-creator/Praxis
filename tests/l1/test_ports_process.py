"""Tests for the ProcessPort exec seam (l1.kernel.ports.process)."""

from __future__ import annotations

import pytest

from l1.kernel.ports import (
    ProcessPort,
    ProcessResult,
    SubprocessProcessPort,
    get_port,
    register_port,
    reset_ports,
)


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


def test_result_ok_property() -> None:
    assert ProcessResult(returncode=0).ok is True
    assert ProcessResult(returncode=1).ok is False
    assert ProcessResult(returncode=0, timed_out=True).ok is False


def test_resolvable_through_registry() -> None:
    reset_ports()
    register_port("process", SubprocessProcessPort())
    resolved = get_port("process")
    assert isinstance(resolved, ProcessPort)
    assert resolved.run("echo seam").stdout.strip() == "seam"
    reset_ports()
