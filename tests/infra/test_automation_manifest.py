"""Tests for automation manifest validation, planning, and execution."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "py"))

from automation_manifest import AutomationManifest, ManifestError  # noqa: E402
from automation_runner import AutomationRunner  # noqa: E402

from l1.kernel.ports.process import ProcessResult  # noqa: E402


def _manifest() -> AutomationManifest:
    """Build a small deterministic workflow for unit tests."""
    return AutomationManifest.from_mapping(
        {
            "automation": {
                "schema_version": 1,
                "defaults": {"timeout_s": 10},
                "workflows": {
                    "test": {
                        "steps": [
                            {"id": "build", "command": ["python", "-V"]},
                            {"id": "check", "depends_on": ["build"], "command": ["python", "-V"]},
                        ]
                    }
                },
            }
        }
    )


def test_default_discovery_manifest_loads() -> None:
    """The shipped discovery file is valid and exposes the performance workflow."""
    manifest = AutomationManifest.load()

    assert manifest.schema_version == 1
    assert [step.step_id for step in manifest.workflow("performance").plan()] == [
        "l2_protocol",
        "perf_quality",
        "r2_baseline_bundle",
        "r2_baseline_analysis",
    ]


def test_manifest_plans_dependencies_first() -> None:
    """The planner emits a stable prerequisites-first order."""
    workflow = _manifest().workflow("test")

    assert [step.step_id for step in workflow.plan()] == ["build", "check"]
    assert workflow.steps[0].argv("/venv/bin/python")[0] == "/venv/bin/python"


def test_manifest_uses_registered_dependency_graph_port() -> None:
    """Manifest planning consumes the stable port when boot wiring is present."""
    from l1.kernel.ports import DependencyGraphPort, register_port, reset_ports

    class FakeGraph(DependencyGraphPort):
        def __init__(self) -> None:
            self.nodes: dict[str, tuple[str, ...]] | None = None

        def plan(self, nodes: dict[str, tuple[str, ...]]) -> list[str]:
            self.nodes = nodes
            return ["build", "check"]

    graph = FakeGraph()
    reset_ports()
    register_port("dependency_graph", graph)
    try:
        workflow = _manifest().workflow("test")
        assert [step.step_id for step in workflow.plan()] == ["build", "check"]
        assert graph.nodes == {"build": (), "check": ("build",)}
    finally:
        reset_ports()


@pytest.mark.parametrize(
    "patch",
    [
        {"schema_version": 2, "defaults": {"timeout_s": 1}, "workflows": {}},
        {
            "schema_version": 1,
            "defaults": {"timeout_s": 1},
            "workflows": {"x": {"steps": [{"id": "a", "depends_on": ["b"], "command": ["python"]}]}},
        },
        {
            "schema_version": 1,
            "defaults": {"timeout_s": 1},
            "workflows": {
                "x": {
                    "steps": [
                        {"id": "a", "depends_on": ["b"], "command": ["python"]},
                        {"id": "b", "depends_on": ["a"], "command": ["python"]},
                    ]
                }
            },
        },
    ],
)
def test_manifest_rejects_invalid_graphs(patch: dict) -> None:
    """Unsupported versions, missing dependencies, and cycles fail closed."""
    with pytest.raises(ManifestError):
        AutomationManifest.from_mapping({"automation": patch})


def test_runner_skips_dependents_after_failure() -> None:
    """A failed step blocks dependent work and preserves the trace id."""
    calls: list[str] = []

    def executor(step):
        calls.append(step.step_id)
        return ProcessResult(returncode=1 if step.step_id == "build" else 0, stderr="failed")

    from l1.kernel.ports import reset_ports

    reset_ports()
    try:
        run = AutomationRunner(executor).run(_manifest().workflow("test"), trace_id="trace-test")
    finally:
        reset_ports()

    assert calls == ["build"]
    assert [step.status for step in run.steps] == ["failed", "skipped"]
    assert all(step.trace_id == "trace-test" for step in run.steps)
    assert not run.ok


def test_runner_uses_side_channel_ports_without_l3_imports() -> None:
    """Metrics, evidence, and trace adapters observe steps without owning execution."""
    from contextlib import contextmanager

    from l1.kernel.ports import EvidencePort, ObservabilityPort, TracePort, register_port, reset_ports

    events: list[tuple[str, str]] = []

    class Metrics(ObservabilityPort):
        def emit_count(self, name: str, value: int = 1, *, tags=None) -> None:
            events.append(("count", name))

        def emit_duration(self, name: str, started: float, *, tags=None) -> None:
            events.append(("duration", name))

    class Evidence(EvidencePort):
        def record_evidence(self, phase: str, **kwargs) -> str:
            events.append(("evidence", phase))
            return "evidence-test"

    class Trace(TracePort):
        @contextmanager
        def scope(self, trace_id: str):
            events.append(("trace-start", trace_id))
            yield trace_id
            events.append(("trace-end", trace_id))

    reset_ports()
    register_port("observability", Metrics())
    register_port("evidence", Evidence())
    register_port("trace", Trace())
    try:
        run = AutomationRunner(lambda step: ProcessResult()).run(_manifest().workflow("test"), trace_id="trace-ports")
    finally:
        reset_ports()

    assert run.ok
    assert ("trace-start", "trace-ports") in events
    assert ("trace-end", "trace-ports") in events
    assert events.count(("evidence", "automation")) == 2
    assert events.count(("count", "automation.step.count")) == 2
