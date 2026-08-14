"""HTN planner — built-in domain decomposition methods (mixin).

Extracted from ``htn_planner.py``: the five built-in decomposition recipes
(develop / build / fix / refactor / review). Each returns a Task subtree
for a compound root; ``HTNPlanner`` composes this mixin.
"""

from __future__ import annotations

from typing import Any

from .htn_models import Task, TaskType


class HTNMethodsMixin:
    """Built-in HTN decomposition recipes — composed by HTNPlanner."""

    # Tool-access attribute provided by the composing HTNPlanner (for mypy).
    _tool: Any

    def _decompose_develop(self, root: Task) -> list[Task]:
        tid = root.id
        t = self._tool
        return [
            Task(
                id=f"{tid}-design",
                task_type=TaskType.COMPOUND,
                domain=root.domain,
                name="Design",
                sub_tasks=[
                    Task(
                        id=f"{tid}-design-req",
                        task_type=TaskType.PRIMITIVE,
                        tool=t("analyze", "read_file"),
                        name="Analyze requirements",
                        description=f"Analyze: {root.name}",
                        domain=root.domain,
                    ),
                    Task(
                        id=f"{tid}-design-arch",
                        task_type=TaskType.PRIMITIVE,
                        tool=t("write", "write_file"),
                        name="Design doc",
                        description="Write design",
                        domain=root.domain,
                        depends_on=[f"{tid}-design-req"],
                    ),
                ],
            ),
            Task(
                id=f"{tid}-impl",
                task_type=TaskType.COMPOUND,
                domain=root.domain,
                name="Implement",
                depends_on=[f"{tid}-design"],
                sub_tasks=[
                    Task(
                        id=f"{tid}-impl-code",
                        task_type=TaskType.PRIMITIVE,
                        tool=t("create", "create_file"),
                        name="Write code",
                        description="Implement",
                        domain=root.domain,
                    ),
                    Task(
                        id=f"{tid}-impl-test",
                        task_type=TaskType.PRIMITIVE,
                        tool=t("create", "create_file"),
                        name="Write tests",
                        domain=root.domain,
                        depends_on=[f"{tid}-impl-code"],
                    ),
                ],
            ),
            Task(
                id=f"{tid}-verify",
                task_type=TaskType.COMPOUND,
                domain=root.domain,
                name="Verify",
                depends_on=[f"{tid}-impl"],
                sub_tasks=[
                    Task(
                        id=f"{tid}-verify-build",
                        task_type=TaskType.PRIMITIVE,
                        tool=t("build", "build_project"),
                        name="Build",
                        domain=root.domain,
                    ),
                    Task(
                        id=f"{tid}-verify-test",
                        task_type=TaskType.PRIMITIVE,
                        tool=t("test", "test_project"),
                        name="Test",
                        domain=root.domain,
                        depends_on=[f"{tid}-verify-build"],
                    ),
                    Task(
                        id=f"{tid}-verify-lint",
                        task_type=TaskType.PRIMITIVE,
                        tool=t("lint", "lint"),
                        name="Lint",
                        domain=root.domain,
                    ),
                ],
            ),
            Task(
                id=f"{tid}-doc",
                task_type=TaskType.PRIMITIVE,
                tool=t("doc", "write_file"),
                name="Documentation",
                domain=root.domain,
                depends_on=[f"{tid}-verify"],
            ),
        ]

    def _decompose_build(self, root: Task) -> list[Task]:
        tid = root.id
        t = self._tool
        return [
            Task(
                id=f"{tid}-lint", task_type=TaskType.PRIMITIVE, tool=t("lint", "lint"), name="Lint", domain=root.domain
            ),
            Task(
                id=f"{tid}-test",
                task_type=TaskType.PRIMITIVE,
                tool=t("test", "test_project"),
                name="Test",
                domain=root.domain,
                depends_on=[f"{tid}-lint"],
            ),
            Task(
                id=f"{tid}-build",
                task_type=TaskType.PRIMITIVE,
                tool=t("build", "build_project"),
                name="Build",
                domain=root.domain,
                depends_on=[f"{tid}-test"],
            ),
        ]

    def _decompose_fix(self, root: Task) -> list[Task]:
        tid = root.id
        t = self._tool
        return [
            Task(
                id=f"{tid}-scout",
                task_type=TaskType.PRIMITIVE,
                tool=t("scout", "scout_delegate"),
                name="Investigate",
                domain=root.domain,
            ),
            Task(
                id=f"{tid}-diagnose",
                task_type=TaskType.PRIMITIVE,
                tool=t("analyze", "read_file"),
                name="Diagnose",
                domain=root.domain,
                depends_on=[f"{tid}-scout"],
            ),
            Task(
                id=f"{tid}-fix",
                task_type=TaskType.PRIMITIVE,
                tool=t("fix", "write_file"),
                name="Fix",
                domain=root.domain,
                depends_on=[f"{tid}-diagnose"],
            ),
            Task(
                id=f"{tid}-verify",
                task_type=TaskType.PRIMITIVE,
                tool=t("test", "test_project"),
                name="Verify",
                domain=root.domain,
                depends_on=[f"{tid}-fix"],
            ),
        ]

    def _decompose_refactor(self, root: Task) -> list[Task]:
        tid = root.id
        t = self._tool
        return [
            Task(
                id=f"{tid}-scout",
                task_type=TaskType.PRIMITIVE,
                tool=t("analyze", "read_file"),
                name="Analyze",
                domain=root.domain,
            ),
            Task(
                id=f"{tid}-plan",
                task_type=TaskType.PRIMITIVE,
                tool=t("write", "write_file"),
                name="Plan",
                domain=root.domain,
                depends_on=[f"{tid}-scout"],
            ),
            Task(
                id=f"{tid}-exec",
                task_type=TaskType.PRIMITIVE,
                tool=t("extract", "write_file"),
                name="Execute",
                domain=root.domain,
                depends_on=[f"{tid}-plan"],
            ),
            Task(
                id=f"{tid}-verify",
                task_type=TaskType.PRIMITIVE,
                tool=t("test", "test_project"),
                name="Verify",
                domain=root.domain,
                depends_on=[f"{tid}-exec"],
            ),
        ]

    def _decompose_review(self, root: Task) -> list[Task]:
        tid = root.id
        t = self._tool
        return [
            Task(
                id=f"{tid}-scan",
                task_type=TaskType.PRIMITIVE,
                tool=t("review", "read_file"),
                name="Scan",
                domain=root.domain,
            ),
            Task(
                id=f"{tid}-analyze",
                task_type=TaskType.PRIMITIVE,
                tool=t("analyze", "read_file"),
                name="Analyze",
                domain=root.domain,
                depends_on=[f"{tid}-scan"],
            ),
            Task(
                id=f"{tid}-report",
                task_type=TaskType.PRIMITIVE,
                tool=t("doc", "write_file"),
                name="Report",
                domain=root.domain,
                depends_on=[f"{tid}-analyze"],
            ),
        ]
