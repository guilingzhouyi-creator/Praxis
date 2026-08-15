"""CI service tests."""

from __future__ import annotations

import os
import sys

from l1.kernel.params.kernel import PROCESS_RETURN_EXECUTION_ERROR
from l1.kernel.ports import ProcessOptions, ProcessPort, ProcessResult, register_port, reset_ports

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _FakeProcessPort(ProcessPort):
    """Process adapter fake that records CI shell requests."""

    name = "test.ci.process"

    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []
        self.options: list[ProcessOptions | None] = []

    def run(self, cmd: str, timeout: float = 0, options: ProcessOptions | None = None) -> ProcessResult:
        """Record a shell command and return the configured result."""
        self.calls.append(("run", cmd))
        self.options.append(options)
        return self.result

    def run_args(self, args: list[str], timeout: float = 0, options: ProcessOptions | None = None) -> ProcessResult:
        """Satisfy the ProcessPort contract; CI does not use argument execution."""
        self.calls.append(("run_args", " ".join(args)))
        self.options.append(options)
        return self.result


class TestCI:
    def test_importable(self):
        from l4.ci import get_service

        assert callable(get_service)

    def test_pipeline_uses_registered_process_adapter(self):
        import l4.ci as ci

        service = ci.CIService()
        run = ci.PipelineRun(run_id="run-1", name="test", steps=[{"action": "echo", "cmd": "echo hello"}])
        service._runs[run.run_id] = run
        fake = _FakeProcessPort(ProcessResult(returncode=0))
        reset_ports()
        try:
            register_port("process", fake)
            service._execute(run.run_id, timeout=30.0)
            assert fake.calls == [("run", "echo hello")]
            assert fake.options == [ProcessOptions(cwd=".")]
            assert run.status == ci.PipelineStatus.PASSED
        finally:
            reset_ports()

    def test_pipeline_translates_process_result_timeout(self):
        import l4.ci as ci

        service = ci.CIService()
        run = ci.PipelineRun(run_id="run-timeout", name="test", steps=[{"action": "echo", "cmd": "echo hello"}])
        service._runs[run.run_id] = run
        reset_ports()
        try:
            register_port("process", _FakeProcessPort(ProcessResult(returncode=-1, timed_out=True)))
            service._execute(run.run_id, timeout=30.0)
            assert run.status == ci.PipelineStatus.TIMEOUT
            assert "timed out" in run.error
        finally:
            reset_ports()

    def test_pipeline_does_not_treat_real_negative_returncode_as_missing_command(self):
        """Preserve a SIGINT-like child returncode instead of reporting not found."""
        import l4.ci as ci

        service = ci.CIService()
        run = ci.PipelineRun(run_id="run-sigint", name="test", steps=[{"action": "echo", "cmd": "echo hello"}])
        service._runs[run.run_id] = run
        reset_ports()
        try:
            register_port("process", _FakeProcessPort(ProcessResult(returncode=PROCESS_RETURN_EXECUTION_ERROR)))
            service._execute(run.run_id, timeout=30.0)
            assert run.status == ci.PipelineStatus.FAILED
            assert "not found" not in run.error
            assert str(PROCESS_RETURN_EXECUTION_ERROR) in run.error
        finally:
            reset_ports()
