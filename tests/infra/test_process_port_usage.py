"""Guard the one-shot process boundary outside L1 adapters."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIRS = (ROOT / "src" / "l2", ROOT / "src" / "l3", ROOT / "src" / "l4")
PLATFORM_EXEC_HELPERS = frozenset({"run_shell", "run_args"})
SUBPROCESS_ONE_SHOT_HELPERS = frozenset({"run", "call", "check_output", "check_call"})


def _runtime_modules() -> list[Path]:
    """Return production Python modules covered by the one-shot process rule."""
    return [path for directory in RUNTIME_DIRS for path in directory.rglob("*.py")]


def _qualified_name(node: ast.expr) -> str:
    """Return a dotted expression name when *node* is composed of attributes."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def _platform_exec_helper_uses(path: Path) -> list[str]:
    """Return direct platform execution imports and module-alias calls."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_aliases: set[str] = set()
    function_aliases: set[str] = set()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "l1.kernel.platform":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "l1.kernel.platform":
            for alias in node.names:
                if alias.name in PLATFORM_EXEC_HELPERS:
                    function_aliases.add(alias.asname or alias.name)
                    offenders.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "l1.kernel":
            for alias in node.names:
                if alias.name == "platform":
                    module_aliases.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in PLATFORM_EXEC_HELPERS:
            if _qualified_name(node.func.value) in module_aliases:
                offenders.append(node.func.attr)
        elif isinstance(node.func, ast.Name) and node.func.id in function_aliases:
            offenders.append(node.func.id)
    return offenders


def test_noninteractive_paths_do_not_import_platform_exec_helpers() -> None:
    """Require L2/L3/L4 one-shot execution to resolve ProcessPort instead."""
    offenders: list[str] = []
    for path in _runtime_modules():
        calls = _platform_exec_helper_uses(path)
        if calls:
            offenders.append(f"{path.relative_to(ROOT)}: {', '.join(sorted(calls))}")
    assert not offenders, "one-shot paths must use ProcessPort:\n" + "\n".join(offenders)


def _subprocess_one_shot_calls(path: Path) -> list[str]:
    """Return direct stdlib one-shot execution calls found in a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_aliases: set[str] = set()
    function_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in SUBPROCESS_ONE_SHOT_HELPERS:
                    function_aliases.add(alias.asname or alias.name)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id in module_aliases and node.func.attr in SUBPROCESS_ONE_SHOT_HELPERS:
                offenders.append(node.func.attr)
        elif isinstance(node.func, ast.Name) and node.func.id in function_aliases:
            offenders.append(node.func.id)
    return offenders


def test_noninteractive_paths_do_not_call_subprocess_one_shot_helpers_directly() -> None:
    """Keep direct stdlib one-shot calls behind ProcessPort, including aliases."""
    offenders: list[str] = []
    for path in _runtime_modules():
        calls = _subprocess_one_shot_calls(path)
        if calls:
            offenders.append(f"{path.relative_to(ROOT)}: {', '.join(sorted(calls))}")
    assert not offenders, "one-shot stdlib calls must use ProcessPort:\n" + "\n".join(sorted(set(offenders)))


def test_subprocess_usage_detector_tracks_import_variants(tmp_path: Path) -> None:
    """Reject module aliases and direct one-shot imports while allowing Popen."""
    candidate = tmp_path / "candidate.py"
    candidate.write_text(
        "\n".join(
            (
                "import subprocess",
                "import subprocess as sp",
                "from subprocess import check_call as call_now",
                "subprocess.run(['echo', 'a'])",
                "sp.check_output(['echo', 'b'])",
                "call_now(['echo', 'c'])",
                "sp.Popen(['echo', 'd'])",
            )
        ),
        encoding="utf-8",
    )
    assert _subprocess_one_shot_calls(candidate) == ["run", "check_output", "call_now"]


def test_platform_usage_detector_tracks_module_alias_variants(tmp_path: Path) -> None:
    """Reject platform execution imports and calls made through module aliases."""
    candidate = tmp_path / "candidate.py"
    candidate.write_text(
        "\n".join(
            (
                "import l1.kernel.platform as p",
                "from l1.kernel import platform as kernel_platform",
                "from l1.kernel.platform import run_args as raw_run_args",
                "p.run_shell('echo a')",
                "kernel_platform.run_args(['echo', 'b'])",
                "raw_run_args(['echo', 'c'])",
            )
        ),
        encoding="utf-8",
    )
    assert _platform_exec_helper_uses(candidate) == ["raw_run_args", "run_shell", "run_args", "raw_run_args"]
