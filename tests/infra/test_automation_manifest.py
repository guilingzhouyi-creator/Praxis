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
    assert [step.step_id for step in manifest.workflow("performance").plan()] == ["l2_protocol", "perf_quality"]


def test_manifest_plans_dependencies_first() -> None:
    """The planner emits a stable prerequisites-first order."""
    workflow = _manifest().workflow("test")

    assert [step.step_id for step in workflow.plan()] == ["build", "check"]
    assert workflow.steps[0].argv("/venv/bin/python")[0] == "/venv/bin/python"


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

    run = AutomationRunner(executor).run(_manifest().workflow("test"), trace_id="trace-test")

    assert calls == ["build"]
    assert [step.status for step in run.steps] == ["failed", "skipped"]
    assert all(step.trace_id == "trace-test" for step in run.steps)
    assert not run.ok
