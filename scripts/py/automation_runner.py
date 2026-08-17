"""Execute automation workflows through Praxis ports with evidence hooks."""

from __future__ import annotations

import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from automation_manifest import AutomationStep, AutomationWorkflow  # noqa: E402

from l1.kernel.ports.process import ProcessOptions, ProcessResult, get_process_port  # noqa: E402

StepExecutor = Callable[[AutomationStep], ProcessResult]


@dataclass(frozen=True, slots=True)
class StepResult:
    """Auditable outcome for one automation step."""

    step_id: str
    status: str
    returncode: int
    duration_ms: float
    trace_id: str
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        """Return whether the step completed successfully."""
        return self.status == "passed"

    def as_dict(self) -> dict[str, Any]:
        """Serialize the step outcome for JSON reports."""
        return {
            "step_id": self.step_id,
            "status": self.status,
            "returncode": self.returncode,
            "duration_ms": round(self.duration_ms, 3),
            "trace_id": self.trace_id,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass(frozen=True, slots=True)
class AutomationRun:
    """Complete workflow result with ordered step outcomes."""

    workflow: str
    trace_id: str
    started_at: float
    finished_at: float
    steps: tuple[StepResult, ...]

    @property
    def ok(self) -> bool:
        """Return whether every planned step passed."""
        return bool(self.steps) and all(step.ok for step in self.steps)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the run for a report artifact."""
        return {
            "workflow": self.workflow,
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "steps": [step.as_dict() for step in self.steps],
        }


def _default_executor(step: AutomationStep) -> ProcessResult:
    """Execute one step through the registered ProcessPort adapter."""
    options = ProcessOptions(cwd=str(ROOT))
    return get_process_port().run_args(step.argv(sys.executable), timeout=step.timeout_s, options=options)


class AutomationRunner:
    """Run a workflow serially while preserving trace, metrics, and evidence."""

    def __init__(self, executor: StepExecutor | None = None) -> None:
        self._executor = executor or _default_executor

    def run(self, workflow: AutomationWorkflow, *, trace_id: str = "", dry_run: bool = False) -> AutomationRun:
        """Execute *workflow* in DAG order and return an auditable result."""
        run_trace = trace_id or uuid.uuid4().hex
        started_at = time.time()
        results: list[StepResult] = []
        failed: set[str] = set()
        plan = workflow.plan()
        trace_scope, emit_count, emit_duration, record_evidence = self._hooks()
        with trace_scope(run_trace):
            for step in plan:
                if any(dependency in failed for dependency in step.depends_on):
                    result = StepResult(step.step_id, "skipped", 1, 0.0, run_trace, stderr="dependency failed")
                    failed.add(step.step_id)
                    results.append(result)
                    continue
                if dry_run:
                    results.append(StepResult(step.step_id, "planned", 0, 0.0, run_trace))
                    continue
                step_started = time.perf_counter()
                try:
                    process = self._executor(step)
                    status = "passed" if process.ok else "failed"
                    returncode = process.returncode
                    stdout = process.stdout
                    stderr = process.stderr
                except Exception as error:
                    status = "failed"
                    returncode = 1
                    stdout = ""
                    stderr = str(error)
                duration_ms = (time.perf_counter() - step_started) * 1000.0
                result = StepResult(step.step_id, status, returncode, duration_ms, run_trace, stdout, stderr)
                results.append(result)
                tags = {"phase": step.step_id, "status": status, "success": str(result.ok).lower()}
                emit_count("automation.step.count", tags=tags)
                emit_duration("automation.step.duration_ms", step_started, tags=tags)
                record_evidence(
                    phase="automation",
                    gate="automation.step",
                    decision="ALLOW" if result.ok else "BLOCK",
                    source="automation_runner",
                    tags={"phase": step.step_id, "status": status},
                    raw={"workflow": workflow.name, "step_id": step.step_id, "returncode": returncode},
                )
                if not result.ok:
                    failed.add(step.step_id)
        return AutomationRun(workflow.name, run_trace, started_at, time.time(), tuple(results))

    @staticmethod
    def _hooks():
        """Resolve best-effort runtime hooks without changing step execution."""
        try:
            from l3.error_bus.trace import trace_scope
            from l3.services.observability import emit_count, emit_duration
            from l3.tool_system.security_evidence import record_evidence

            return trace_scope, emit_count, emit_duration, record_evidence
        except Exception:
            from contextlib import contextmanager

            @contextmanager
            def trace_scope(trace_id: str):
                yield trace_id

            return trace_scope, lambda *args, **kwargs: None, lambda *args, **kwargs: None, lambda *args, **kwargs: ""
