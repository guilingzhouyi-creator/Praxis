"""Scan src/ for module-level singleton patterns (_xxx = None) with getters.

A module-level ``_xxx = None`` (plain or annotated) paired with a
``get_xxx()``-style accessor is a real global singleton that can leak
across tests — it needs a reset in ``tests/conftest.py`` ``_RESETS`` (or
an explicit exemption with a reason). Plain ``_xxx = None`` without an
accessor is usually an inert default.

Run from the repo root:

    python scripts/py/scan-singletons.py

Every newly reported singleton should be judged: add a reset function +
``_RESETS`` entry, or document why it is exempt. The completeness guard
(``tests/infra/test_resets_completeness.py``) consumes ``scan()`` so a new
singleton fails CI unless it is registered or exempted.
"""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _module_singletons(tree: ast.Module):
    """Yield names of module-level `_xxx = None` assignments (plain + annotated)."""
    for node in tree.body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target
        else:
            continue
        if not isinstance(target, ast.Name) or not target.id.startswith("_") or target.id.startswith("__"):
            continue
        if not (isinstance(node.value, ast.Constant) and node.value.value is None):
            continue
        yield target.id


def _module_name(py: pathlib.Path) -> str:
    """Map a src/ path to its dotted module name (handles __init__.py)."""
    rel = py.relative_to(ROOT / "src")
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


def scan() -> dict:
    """Scan src/ and return structured singleton data.

    Returns:
        {
          "total": int,
          "with_getter": [(module, var), ...],   # real singletons
          "registered": {module, ...},           # modules in conftest _RESETS
          "gaps": [(module, var), ...],          # with_getter minus registered
        }
    """
    src = ROOT / "src"
    resets_text = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    registered = set(re.findall(r'"([a-z0-9_.]+)": \("', resets_text))

    total = 0
    with_getter: list[tuple[str, str]] = []
    for py in sorted(src.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        mod = _module_name(py)
        funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for var in _module_singletons(tree):
            total += 1
            base = var[1:]
            if any(base in f for f in funcs):
                with_getter.append((mod, var))

    gaps = [(m, v) for m, v in with_getter if m not in registered]
    return {
        "total": total,
        "with_getter": with_getter,
        "registered": registered,
        "gaps": gaps,
    }


def main() -> None:
    data = scan()
    print(f"total _xxx = None: {data['total']}")
    print(f"with getter (real singletons): {len(data['with_getter'])}")
    print(f"registered modules in _RESETS: {len(data['registered'])}")
    print("--- singletons WITHOUT a reset module (potential gaps) ---")
    for m, v in data["gaps"]:
        print(f"  {m}:{v}")
    print(f"gap count: {len(data['gaps'])}")


if __name__ == "__main__":
    main()
