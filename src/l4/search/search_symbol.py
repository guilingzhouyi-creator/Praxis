"""Search engine — AST-level symbol backend.

Extracted from ``search_engine.py``: code symbol query (classes / functions
/ variables) with a per-file AST cache invalidated by mtime.
"""

from __future__ import annotations

import ast
import logging
import threading
from pathlib import Path

from l1.kernel.discovery import get_service_limit
from l1.kernel.params.system import (
    LOG_TRUNC_200,
    SEARCH_CACHE_MAX,
    SEARCH_SYMBOL_ASSIGN_MATCH,
    SEARCH_SYMBOL_EXACT_MATCH,
    SEARCH_SYMBOL_PARTIAL_MATCH,
    SYMBOL_SEARCH_RESULTS,
)

from .search_models import SearchResult, is_ignored_path

logger = logging.getLogger(__name__)


class SymbolSearch:
    """AST-level code symbol search — find classes/functions/variables across projects.

    Caches parsed AST trees per file, invalidated by mtime change,
    to avoid O(N) re-parsing on repeated searches.
    """

    _ast_cache: dict[tuple[str, float], ast.Module] = {}  # (path, mtime) → AST
    _CACHE_MAX = SEARCH_CACHE_MAX

    LANGUAGES: dict[str, tuple[str, list[str]]] = {
        "python": ("python", [".py"]),
        "javascript": ("javascript", [".js", ".jsx", ".mjs"]),
        "typescript": ("typescript", [".ts", ".tsx"]),
    }

    def __init__(self):
        self._lock = threading.Lock()
        # Declarative override via config/discovery/service_limits.yaml,
        # params constant as fallback (AGENTS.md three-layer config).
        self._cache_max = get_service_limit("search_cache_max", SEARCH_CACHE_MAX)

    def search(self, name: str, kind: str = "", root_dir: str = ".", max_results: int = SYMBOL_SEARCH_RESULTS) -> dict:
        """Search for code symbols."""
        root = Path(root_dir).resolve()
        if not root.exists():
            return {"success": False, "error": f"directory not found: {root_dir}"}

        term = name.lower()
        results: list[SearchResult] = []

        # Python3 AST search — use cached AST with mtime invalidation
        for file_path in root.rglob("*.py"):
            if is_ignored_path(file_path):
                continue
            try:
                mtime = file_path.stat().st_mtime
                cache_key = (str(file_path), mtime)
                cached = self._ast_cache.get(cache_key)
                if cached is not None:
                    tree = cached
                else:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(content)
                    # LRU eviction: keep cache bounded
                    if len(self._ast_cache) >= self._cache_max:
                        # Remove oldest entry (dict preserves insertion order in 3.7+)
                        self._ast_cache.pop(next(iter(self._ast_cache)))
                    self._ast_cache[cache_key] = tree
                for node in ast.walk(tree):
                    match = None
                    if isinstance(node, ast.FunctionDef) and term in node.name.lower():
                        if kind and kind not in ("function", "method", ""):
                            continue
                        match = SearchResult(
                            path=str(file_path.relative_to(root)),
                            line=node.lineno or 1,
                            content=ast.unparse(node).splitlines()[0][:LOG_TRUNC_200]
                            if hasattr(ast, "unparse")
                            else f"def {node.name}(...):",
                            score=SEARCH_SYMBOL_EXACT_MATCH
                            if node.name.lower() == term
                            else SEARCH_SYMBOL_PARTIAL_MATCH,
                            kind="symbol",
                            symbol_name=node.name,
                            symbol_type="method" if self._is_method(node) else "function",
                        )
                    elif isinstance(node, ast.ClassDef) and term in node.name.lower():
                        if kind and kind != "class":
                            continue
                        match = SearchResult(
                            path=str(file_path.relative_to(root)),
                            line=node.lineno or 1,
                            content=f"class {node.name}:",
                            score=SEARCH_SYMBOL_EXACT_MATCH
                            if node.name.lower() == term
                            else SEARCH_SYMBOL_PARTIAL_MATCH,
                            kind="symbol",
                            symbol_name=node.name,
                            symbol_type="class",
                        )
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and term in target.id.lower():
                                match = SearchResult(
                                    path=str(file_path.relative_to(root)),
                                    line=node.lineno or 1,
                                    content=f"{target.id} = ...",
                                    score=SEARCH_SYMBOL_ASSIGN_MATCH,
                                    kind="symbol",
                                    symbol_name=target.id,
                                    symbol_type="variable",
                                )
                                break

                    if match:
                        results.append(match)

            except SyntaxError:
                continue
            except Exception:
                continue

        # Deduplicate + sort
        seen: set[tuple[str, int, str]] = set()
        unique: list[SearchResult] = []
        for r in results:
            key = (r.path, r.line, r.symbol_name)
            if key not in seen:
                seen.add(key)
                unique.append(r)

        unique.sort(key=lambda r: -r.score)
        top = unique[:max_results]

        return {
            "success": True,
            "query": name,
            "kind": kind or "any",
            "total_matches": len(unique),
            "results": [r.to_dict() for r in top],
        }

    def _is_method(self, node: ast.FunctionDef) -> bool:
        """Determine if a function is a method inside a class (check parent node)."""
        for n in ast.walk(node):
            if isinstance(n, ast.ClassDef):
                for item in n.body:
                    if item is node:
                        return True
        return False

    def symbols_in_file(self, file_path: str, root_dir: str = ".") -> dict:
        """Extract AST symbols from a single file (review-context helper, 2.1).

        The review department correlates diff hunks with the symbols they
        touch (function/class/variable definitions + line numbers) without
        re-parsing — the AST cache from ``search()`` is reused, keyed by
        (path, mtime). Degrades gracefully: syntax errors or unsupported
        files return an empty symbol list, never raise.

        Returns:
            ``{"success": bool, "path": ..., "symbols": [{"name", "type",
            "line", "content"}]}``.
        """
        try:
            from pathlib import Path as _Path

            p = (
                _Path(file_path).resolve()
                if _Path(file_path).is_absolute()
                else (_Path(root_dir).resolve() / file_path)
            )
            if not p.exists() or p.suffix not in self.LANGUAGES["python"][1] or is_ignored_path(p):
                return {"success": False, "path": str(file_path), "symbols": []}
            mtime = p.stat().st_mtime
            cache_key = (str(p), mtime)
            cached = self._ast_cache.get(cache_key)
            if cached is not None:
                tree = cached
            else:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
                if len(self._ast_cache) >= self._cache_max:
                    self._ast_cache.pop(next(iter(self._ast_cache)))
                self._ast_cache[cache_key] = tree
            symbols = []

            def _collect(node: ast.AST, in_class: bool) -> None:
                """Collect top-level + class-level symbols with parent context.

                ``in_class`` tracks whether a FunctionDef is a method (the
                shared ``_is_method`` has no parent pointers and cannot tell).
                Function bodies are not descended into — nested helpers stay
                hidden from the review context.
                """
                if isinstance(node, ast.FunctionDef):
                    symbols.append(
                        {
                            "name": node.name,
                            "type": "method" if in_class else "function",
                            "line": node.lineno or 1,
                            "content": (
                                ast.unparse(node).splitlines()[0][:LOG_TRUNC_200]
                                if hasattr(ast, "unparse")
                                else f"def {node.name}(...):"
                            ),
                        }
                    )
                    return
                if isinstance(node, ast.ClassDef):
                    symbols.append(
                        {
                            "name": node.name,
                            "type": "class",
                            "line": node.lineno or 1,
                            "content": f"class {node.name}:",
                        }
                    )
                    for child in ast.iter_child_nodes(node):
                        _collect(child, True)
                    return
                for child in ast.iter_child_nodes(node):
                    _collect(child, in_class)

            _collect(tree, False)
            return {"success": True, "path": str(file_path), "symbols": symbols}
        except SyntaxError:
            return {"success": False, "path": str(file_path), "symbols": []}
        except Exception:
            return {"success": False, "path": str(file_path), "symbols": []}
