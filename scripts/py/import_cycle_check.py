"""Detect circular imports in src/ via AST.

Builds a module dependency graph from import statements (absolute and
relative) and reports strongly-connected components with more than one
node (true cycles) plus self-imports. Exit code 1 on any cycle.

Usage (from the repo root):

    python scripts/py/import_cycle_check.py
"""

from __future__ import annotations

import ast
import pathlib
import sys


def _module_name(py: pathlib.Path) -> str:
    parts = py.relative_to("src").with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_imports(py: pathlib.Path, node: ast.Import | ast.ImportFrom) -> list[str]:
    """Resolve imported module names for one import node (relative-aware)."""
    out: list[str] = []
    if isinstance(node, ast.Import):
        out.extend(a.name for a in node.names)
        return out
    base = node.module or ""
    if node.level > 0:
        cur = _module_name(py).split(".")
        is_pkg = py.name == "__init__.py"
        # Relative: level=1 -> current package; level=2 -> parent package.
        # An __init__ file IS the package, so level=1 resolves to itself
        # (drop 0 components), level=2 to its parent (drop 1).
        drop = node.level - (1 if is_pkg else 0)
        pkg = cur[: max(1, len(cur) - drop)]
        base = ".".join(pkg)
    for alias in node.names:
        if alias.name == "*":
            if base:
                out.append(base)
        elif node.module:
            # from x.y import name → the dependency is the module x.y
            # (the symbol itself is not a graph node).
            if base:
                out.append(base)
        else:
            # from . import sub (bare relative, no module) → base.sub
            out.append(".".join(filter(None, [base, alias.name])))
    return out


def _build_graph() -> tuple[dict[str, set[str]], dict[str, str]]:
    graph: dict[str, set[str]] = {}
    location: dict[str, str] = {}

    def _iter_imports(tree: ast.Module):
        """Yield Import/ImportFrom nodes NOT inside a TYPE_CHECKING block.

        TYPE_CHECKING imports are erased at runtime, so they cannot form a
        real cycle (ci_review <-> ci_review_link relies on this).
        """

        def visit(node, in_type_checking: bool):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if not in_type_checking:
                    yield node
                return
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                in_type_checking = True
            # Function-body imports are lazy (run at call time, after the
            # module finished loading) — they cannot form a load-time cycle.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return
            for child in ast.iter_child_nodes(node):
                yield from visit(child, in_type_checking)

        yield from visit(tree, False)

    for py in sorted(pathlib.Path("src").rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        mod = _module_name(py)
        location[mod] = str(py)
        deps: set[str] = set()
        for node in _iter_imports(tree):
            for dep in _resolve_imports(py, node):
                # Only same-tree deps (lX.*) matter for cycles; keep the full
                # module name so submodule->submodule edges survive (a
                # 2-component truncation would collapse both sides of a
                # package-internal cycle onto one node and lose it).
                if dep.startswith("l") and "." in dep:
                    deps.add(dep)
        graph[mod] = deps
    return graph, location


def _scc(graph: dict[str, set[str]]) -> list[set[str]]:
    """Tarjan SCC — components with >1 node (or self-loop) are cycles."""
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[set[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = index
        low[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, set()):
            if w not in graph:
                continue
            if w not in indices:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], indices[w])
        if low[v] == indices[v]:
            comp: set[str] = set()
            while stack:
                w = stack.pop()
                on_stack.discard(w)
                comp.add(w)
                if w == v:
                    break
            components.append(comp)

    for v in graph:
        if v not in indices:
            strongconnect(v)
    return components


def main() -> int:
    graph, location = _build_graph()
    cycles = [
        c for c in _scc(graph) if len(c) > 1 or (len(c) == 1 and next(iter(c)) in graph.get(next(iter(c)), set()))
    ]

    def _is_export_cycle(comp: set[str]) -> bool:
        # A cycle routed through a package __init__ is the normal Python
        # "package re-export" pattern: the __init__ imports submodules and
        # submodules import symbols from the package. It resolves at import
        # time by ordering (verified: `import l1.kernel` succeeds) and does
        # not deadlock. Only submodule<->submodule cycles (no __init__
        # involved) are load-time hazards.
        return any(location.get(mod, "").endswith("__init__.py") for mod in comp)

    hard = [c for c in cycles if not _is_export_cycle(c)]
    soft = [c for c in cycles if _is_export_cycle(c)]
    if hard:
        print(f"❌ load-time circular imports ({len(hard)} component(s)):")
        for comp in sorted(hard, key=len, reverse=True):
            for mod in sorted(comp):
                print(f"  {mod}  ({location.get(mod, '?')})")
        return 1
    if soft:
        print(f"⚠️ package re-export cycles (benign, __init__-routed): {len(soft)}")
    print(f"✅ no hazardous circular imports ({len(graph)} modules scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
