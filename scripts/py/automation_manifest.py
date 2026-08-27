"""Load and plan declarative automation workflows."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "config" / "discovery" / "automation.yaml"
SRC = ROOT / "systems/python-reference-runtime"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class ManifestError(ValueError):
    """Raised when an automation manifest violates its structural contract."""


@dataclass(frozen=True, slots=True)
class AutomationStep:
    """One bounded, argument-array automation command."""

    step_id: str
    command: tuple[str, ...]
    depends_on: tuple[str, ...]
    timeout_s: float

    def argv(self, python_executable: str) -> list[str]:
        """Return the command with the active interpreter resolved."""
        if not self.command:
            return []
        command = list(self.command)
        if command[0] in {"python", "python3"}:
            command[0] = python_executable
        return command


@dataclass(frozen=True, slots=True)
class AutomationWorkflow:
    """Named workflow containing steps and dependency edges."""

    name: str
    description: str
    steps: tuple[AutomationStep, ...]

    @property
    def step_map(self) -> dict[str, AutomationStep]:
        """Return steps keyed by their stable identifiers."""
        return {step.step_id: step for step in self.steps}

    def plan(self) -> list[AutomationStep]:
        """Return a deterministic prerequisites-first execution plan."""
        steps = self.step_map
        dvg_plan = self._dvg_plan(steps)
        if dvg_plan is not None:
            return dvg_plan
        state: dict[str, int] = {}
        ordered: list[AutomationStep] = []

        def visit(step_id: str, chain: tuple[str, ...] = ()) -> None:
            """Visit one dependency node and fail closed on invalid graphs."""
            status = state.get(step_id, 0)
            if status == 2:
                return
            if status == 1:
                loop = " -> ".join((*chain, step_id))
                raise ManifestError(f"workflow '{self.name}' contains a dependency cycle: {loop}")
            step = steps.get(step_id)
            if step is None:
                parent = chain[-1] if chain else self.name
                raise ManifestError(f"workflow '{self.name}' step '{parent}' depends on unknown step '{step_id}'")
            state[step_id] = 1
            for dependency in step.depends_on:
                visit(dependency, (*chain, step_id))
            state[step_id] = 2
            ordered.append(step)

        for step in self.steps:
            visit(step.step_id)
        return ordered

    def _dvg_plan(self, steps: dict[str, AutomationStep]) -> list[AutomationStep] | None:
        """Use the registered dependency-graph port, with a standalone fallback."""
        if any(dependency not in steps for step in steps.values() for dependency in step.depends_on):
            return None
        try:
            from l1.kernel.ports import DependencyGraphPort, get_port

            graph_port = get_port("dependency_graph")
            if not isinstance(graph_port, DependencyGraphPort):
                return None
        except Exception:
            return None
        try:
            ordered_names = graph_port.plan({step_id: step.depends_on for step_id, step in steps.items()})
        except ValueError as error:
            raise ManifestError(f"workflow '{self.name}' dependency graph is invalid: {error}") from error
        if set(ordered_names) != set(steps) or len(ordered_names) != len(steps):
            raise ManifestError(f"workflow '{self.name}' dependency graph returned an invalid order")
        return [steps[name] for name in ordered_names]


@dataclass(frozen=True, slots=True)
class AutomationManifest:
    """Schema-versioned collection of named automation workflows."""

    schema_version: int
    defaults: dict[str, Any]
    workflows: dict[str, AutomationWorkflow]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> AutomationManifest:
        """Build a validated manifest from a YAML-shaped mapping."""
        root = data.get("automation", data)
        if not isinstance(root, dict):
            raise ManifestError("automation manifest must be a mapping")
        version = root.get("schema_version")
        if version != 1:
            raise ManifestError(f"unsupported automation schema_version: {version!r}")
        defaults = root.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ManifestError("automation.defaults must be a mapping")
        default_timeout = defaults.get("timeout_s")
        if not isinstance(default_timeout, (int, float)) or default_timeout <= 0:
            raise ManifestError("automation.defaults.timeout_s must be a positive number")
        raw_workflows = root.get("workflows") or {}
        if not isinstance(raw_workflows, dict) or not raw_workflows:
            raise ManifestError("automation.workflows must contain at least one workflow")

        workflows: dict[str, AutomationWorkflow] = {}
        for name, raw_workflow in raw_workflows.items():
            if not isinstance(name, str) or not name.strip():
                raise ManifestError("workflow names must be non-empty strings")
            if not isinstance(raw_workflow, dict):
                raise ManifestError(f"workflow '{name}' must be a mapping")
            raw_steps = raw_workflow.get("steps")
            if not isinstance(raw_steps, list) or not raw_steps:
                raise ManifestError(f"workflow '{name}' must define a non-empty steps list")
            steps: list[AutomationStep] = []
            seen: set[str] = set()
            for raw_step in raw_steps:
                if not isinstance(raw_step, dict):
                    raise ManifestError(f"workflow '{name}' contains a non-mapping step")
                step_id = raw_step.get("id")
                command = raw_step.get("command")
                if not isinstance(step_id, str) or not step_id.strip():
                    raise ManifestError(f"workflow '{name}' has a step without a valid id")
                if step_id in seen:
                    raise ManifestError(f"workflow '{name}' duplicates step '{step_id}'")
                if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
                    raise ManifestError(f"workflow '{name}' step '{step_id}' command must be a non-empty string list")
                dependencies = raw_step.get("depends_on", [])
                if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
                    raise ManifestError(f"workflow '{name}' step '{step_id}' depends_on must be a string list")
                timeout = raw_step.get("timeout_s", default_timeout)
                if not isinstance(timeout, (int, float)) or timeout <= 0:
                    raise ManifestError(f"workflow '{name}' step '{step_id}' timeout_s must be positive")
                steps.append(AutomationStep(step_id, tuple(command), tuple(dependencies), float(timeout)))
                seen.add(step_id)
            workflow = AutomationWorkflow(name, str(raw_workflow.get("description", "")), tuple(steps))
            workflow.plan()
            workflows[name] = workflow
        return cls(int(version), dict(defaults), workflows)

    @classmethod
    def load(cls, path: str | os.PathLike[str] = DEFAULT_MANIFEST) -> AutomationManifest:
        """Load and validate a YAML manifest from *path*."""
        manifest_path = Path(path)
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except OSError as error:
            raise ManifestError(f"cannot read automation manifest '{manifest_path}': {error}") from error
        except yaml.YAMLError as error:
            raise ManifestError(f"cannot parse automation manifest '{manifest_path}': {error}") from error
        if not isinstance(data, dict):
            raise ManifestError("automation manifest root must be a mapping")
        return cls.from_mapping(data)

    def workflow(self, name: str) -> AutomationWorkflow:
        """Return a named workflow or raise a validation error."""
        try:
            return self.workflows[name]
        except KeyError as error:
            raise ManifestError(f"unknown automation workflow: {name}") from error
