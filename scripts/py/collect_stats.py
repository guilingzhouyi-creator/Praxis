"""Unified codebase statistics collector — single source of truth.

All counting that feeds generated docs (the architecture stats snapshot and
the llms indexes) lives here so ``gen-doc-stats.py``, ``gen-llms-txt.py`` and
``check-doc-stats.py`` share ONE implementation instead of duplicating
counters. Import as a normal module from ``scripts/py`` (add ``scripts/py`` to
``sys.path``) or load by path with ``importlib``:

    sys.path.insert(0, str(ROOT / "scripts" / "py"))
    from collect_stats import collect_stats, count_files
"""

from __future__ import annotations

import ast
import contextlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"

LAYERS = {
    "l1/kernel": "L1 Kernel",
    "l2": "L2 Shell",
    "l3": "L3 Cell",
    "l4": "L4 Bridge",
    "l5": "L5 User",
}
SUB_LAYERS = {
    "l3/cell/peers/l3a": "L3A (peers)",
    "l3/memory": "L3 Memory",
    "l3/card": "L3 Card",
    "l3/services": "L3 Services",
    "l3/bus": "L3 Bus",
    "l3/agent": "L3 Agent",
    "l4/api_handlers": "L4 Handlers",
}


def py_files(path: Path) -> list[Path]:
    """All .py files under ``path``, excluding ``__pycache__``."""
    return sorted(p for p in path.rglob("*.py") if "__pycache__" not in str(p))


def count_lines(path: Path) -> int:
    """Total line count of .py files under ``path``."""
    total = 0
    for p in py_files(path):
        with contextlib.suppress(OSError, UnicodeDecodeError):
            total += sum(1 for _ in p.open(encoding="utf-8"))
    return total


def count_files(rel: str) -> int:
    """Number of .py files under ``src/<rel>``."""
    return len(py_files(SRC / rel))


def test_stats() -> tuple[int, int]:
    """Return (test files, test cases) under ``tests/``.

    Test files match ``test_*.py``; test cases are functions/methods whose
    name starts with ``test_`` (AST count, same convention as pytest).
    """
    tests = ROOT / "tests"
    files = sorted(p for p in tests.rglob("test_*.py") if "__pycache__" not in str(p))
    cases = 0
    for p in files:
        with contextlib.suppress(OSError, UnicodeDecodeError):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            cases += sum(
                1
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
            )
    return len(files), cases


def long_functions() -> int:
    """Count src/ functions longer than 200 lines (mega-function smell)."""
    count = 0
    for p in py_files(SRC):
        with contextlib.suppress(OSError, UnicodeDecodeError):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = getattr(n, "end_lineno", n.lineno)
                    if end - n.lineno > 200:
                        count += 1
    return count


def comment_ratio() -> float:
    """Fraction of lines starting with ``#`` across src/ (docstrings excluded)."""
    total = 0
    comments = 0
    for p in py_files(SRC):
        with contextlib.suppress(OSError, UnicodeDecodeError):
            for line in p.open(encoding="utf-8"):
                total += 1
                if line.lstrip().startswith("#"):
                    comments += 1
    return round(comments / max(total, 1), 4)


def third_party_imports() -> list[str]:
    """Sorted third-party import names actually used in src/.

    Only names that resolve to a declared dependency in ``pyproject.toml``
    are reported (import alias → package mapping, e.g. ``yaml``→PyYAML,
    ``websocket``→websocket-client); stdlib, the local ``l1``..``l5``
    packages and internal aliases (e.g. ``agent.xxx``) are excluded — a
    dependency audit input.
    """
    stdlib = set(sys.stdlib_module_names)
    local = {"l1", "l2", "l3", "l4", "l5"}

    # Declared deps from pyproject.toml `[project] dependencies`, lowercased.
    declared: list[str] = []
    try:
        import tomllib

        with (ROOT / "pyproject.toml").open("rb") as f:
            pyproject = tomllib.load(f)
        for dep in pyproject.get("project", {}).get("dependencies", []):
            # Strip version spec: "PyYAML>=6.0.3" -> "pyyaml"
            name = dep.split(";", 1)[0].strip()
            for sep in ("<", ">", "=", "~", "!", " "):
                name = name.split(sep, 1)[0].strip()
            if name:
                declared.append(name.lower())
    except Exception:
        pass

    def matches_declared(top: str) -> bool:
        top_l = top.lower()
        return any(top_l == d or d.startswith(top_l) or top_l.startswith(d) for d in declared)

    found: set[str] = set()
    for p in py_files(SRC):
        with contextlib.suppress(OSError, UnicodeDecodeError):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        top = a.name.split(".")[0]
                        if top not in stdlib and top not in local and matches_declared(top):
                            found.add(top)
                elif isinstance(n, ast.ImportFrom) and n.module and not n.module.startswith("."):
                    top = n.module.split(".")[0]
                    if top not in stdlib and top not in local and matches_declared(top):
                        found.add(top)
    return sorted(found)


def yaml_command_count() -> int:
    """Count top-level command keys in ``config/commands.yaml``."""
    text = (ROOT / "config" / "commands.yaml").read_text(encoding="utf-8")
    return len(re.findall(r"^[a-z_][a-z0-9_]*:", text, re.MULTILINE))


def code_registered_command_count() -> int:
    """Count ``_cmd_*`` handlers NOT defined in commands.yaml.

    These are pure code-registered commands (e.g. ``/agents-md``,
    ``/model-spec``) — YAML commands have their own definitions, so the
    handler set minus the YAML command set is the code-only surface.
    """
    text = (ROOT / "config" / "commands.yaml").read_text(encoding="utf-8")
    yaml_cmds = set(re.findall(r"^([a-z_][a-z0-9_]*):", text, re.MULTILINE))
    names: set[str] = set()
    for py in sorted((SRC / "l2" / "l2_shell" / "commands").rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        names.update(re.findall(r"def (_cmd_\w+)", py.read_text(encoding="utf-8")))
    return len({h[5:] for h in names} - yaml_cmds)


def health_scores(stats: dict) -> dict:
    """Normalize key quality dimensions to 0–1 scores with a grade.

    Mapping rules (documented in README "Health" table):
      - test_density : test_cases per 1k code lines (>=15 → 1.0, <=2 → 0.0)
      - long_functions : mega-functions >200 lines (0 → 1.0, >=12 → 0.0)
      - comment_ratio : 0.05–0.30 sweet spot (else degrades to 0.0)
      - third_party : declared deps used (<=6 → 1.0, >=20 → 0.0)
    Overall = mean; grade A>=0.8, B>=0.6, C>=0.4, else D.
    """

    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    code_lines = sum(total for _n, total in stats["layers"].values())
    test_density = stats["test_cases"] / max(code_lines / 1000.0, 1e-9)
    scores = {
        "test_density": clamp01((test_density - 2) / 13.0),
        "long_functions": clamp01(1.0 - stats["long_functions"] / 12.0),
        "comment_ratio": clamp01(1.0 - abs(stats["comment_ratio"] - 0.175) / 0.175),
        "third_party": clamp01(1.0 - len(stats["third_party_imports"]) / 20.0),
    }
    overall = sum(scores.values()) / len(scores)
    grade = "A" if overall >= 0.8 else "B" if overall >= 0.6 else "C" if overall >= 0.4 else "D"
    return {"scores": scores, "overall": round(overall, 3), "grade": grade}


def collect_stats() -> dict:
    """Collect all architecture statistics from the live codebase."""
    sys.path.insert(0, str(SRC))
    stats: dict[str, tuple[int, int]] = {}
    for rel in LAYERS:
        stats[rel] = (len(py_files(SRC / rel)), count_lines(SRC / rel))
    substats: dict[str, tuple[int, int]] = {}
    for rel in SUB_LAYERS:
        substats[rel] = (len(py_files(SRC / rel)), count_lines(SRC / rel))

    routes = 0
    try:
        from l4.api.api_routes import API_ROUTES

        routes = len(API_ROUTES)
    except Exception:
        pass

    params = py_files(SRC / "l1/kernel/params")
    # Constant modules only (exclude package __init__.py) — matches the
    # "8 params/ modules" convention used in AGENTS.md and README.
    const_modules = [p for p in params if p.name != "__init__.py"]
    consts = 0
    try:
        for p in params:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            consts += sum(
                1
                for n in tree.body
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id.isupper()
            )
    except Exception:
        pass

    domains: dict[str, int] = {}
    try:
        from l4.api.api_endpoints import _infer_domain

        for _m, p, _h, _d in API_ROUTES:
            d = _infer_domain(p)
            domains[d] = domains.get(d, 0) + 1
    except Exception:
        pass

    t_files, t_cases = test_stats()
    deps = third_party_imports()

    return {
        "layers": {name: stats[rel] for rel, name in LAYERS.items()},
        "sub": {name: substats[rel] for rel, name in SUB_LAYERS.items()},
        "routes": routes,
        "params_modules": len(const_modules),
        "params_constants": consts,
        "domains": dict(sorted(domains.items(), key=lambda x: -x[1])),
        "commands_yaml": yaml_command_count(),
        "commands_code": code_registered_command_count(),
        "tools_impl": count_files("l3/tools"),
        "cell_components": count_files("l3/cell/components"),
        "test_files": t_files,
        "test_cases": t_cases,
        "long_functions": long_functions(),
        "comment_ratio": comment_ratio(),
        "third_party_imports": deps,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(collect_stats(), indent=2, default=str))
