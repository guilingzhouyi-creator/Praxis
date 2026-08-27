"""Search Engine — Semantic Search + Symbol Search + API Documentation Search

Three-layer search:
  1. SemanticSearch  — keyword + TF-IDF ranking (lightweight, no external dependencies)
  2. SymbolSearch    — AST-level code symbol query (cross-project classes/functions/variables)
  3. DocSearch       — API documentation indexing + search

Module layout (split for readability):
  search_models.py   — SearchResult / DocEntry records + shared ignore helper
  search_semantic.py — SemanticSearch (TF-IDF backend)
  search_symbol.py   — SymbolSearch (AST backend)
  search_docs.py     — DocSearch (docs index backend)
  search_engine.py   — SearchEngine facade + singleton + API handlers

API:
  POST /api/search/semantic — semantic code search
  POST /api/search/symbol   — search code symbols
  POST /api/search/docs     — search API documentation
  POST /api/search          — unified search entry (automatically picks the best approach)
"""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path

from l1.kernel.params.system import (
    DOC_SEARCH_RESULTS,
    SEARCH_DEFAULT_RESULTS,
    SYMBOL_SEARCH_RESULTS,
)

from .search_docs import DocSearch  # noqa: F401 — re-export
from .search_models import DocEntry, SearchResult  # noqa: F401 — re-export
from .search_semantic import SemanticSearch  # noqa: F401 — re-export
from .search_symbol import SymbolSearch  # noqa: F401 — re-export

logger = __import__("logging").getLogger(__name__)


class SearchEngine:
    """Unified search entry — automatically selects the best search method."""

    def __init__(self):
        self._semantic = SemanticSearch()
        self._symbol = SymbolSearch()
        self._docs = DocSearch()
        self._lock = threading.Lock()

    def search(
        self, query: str, mode: str = "auto", root_dir: str = ".", max_results: int = SEARCH_DEFAULT_RESULTS
    ) -> dict:
        """Unified search entry.

        mode:
          "auto"     — smart selection (uppercase/dot → symbol search; import/lib → doc search; otherwise
                       semantic search)
          "semantic" — semantic search
          "symbol"   — symbol search
          "docs"     — doc search
        """
        if mode == "semantic":
            return self._semantic.search(query, root_dir, max_results=max_results)
        if mode == "symbol":
            return self._symbol.search(query, root_dir=root_dir, max_results=max_results)
        if mode == "docs":
            return self._docs.search(query, max_results=max_results)
        return self._search_auto(query, root_dir, max_results)

    def _search_auto(self, query: str, root_dir: str, max_results: int) -> dict:
        """Smart selection — symbol/doc for dotted or uppercase queries, doc for import-ish, else semantic."""
        if "." in query or query[0].isupper():
            sym_r = self._symbol.search(query, root_dir=root_dir, max_results=max_results)
            if sym_r.get("total_matches", 0) > 0:
                return sym_r
            doc_r = self._docs.search(query, max_results=max_results)
            if doc_r.get("total", 0) > 0:
                return doc_r
        elif any(kw in query.lower() for kw in ("import ", "lib.", "api.")):
            return self._docs.search(query, max_results=max_results)

        return self._semantic.search(query, root_dir, max_results=max_results)

    def semantic_search(
        self, query: str, root_dir: str = ".", file_pattern: str = "*.py", max_results: int = SEARCH_DEFAULT_RESULTS
    ) -> dict:
        """Run a semantic (TF-IDF) keyword search over the directory."""
        return self._semantic.search(query, root_dir, file_pattern, max_results)

    def symbol_search(
        self, name: str, kind: str = "", root_dir: str = ".", max_results: int = SYMBOL_SEARCH_RESULTS
    ) -> dict:
        """Search for code symbols by name, optionally filtered by kind."""
        return self._symbol.search(name, kind, root_dir, max_results)

    def doc_search(self, query: str, max_results: int = DOC_SEARCH_RESULTS) -> dict:
        """Search the indexed API documentation entries."""
        return self._docs.search(query, max_results)

    def index_doc(
        self, package: str, module: str, name: str, signature: str = "", docstring: str = "", url: str = ""
    ) -> dict:
        """Index an API documentation entry for doc search."""
        return self._docs.index(package, module, name, signature, docstring, url)


# ── Global singleton ──

_engine: SearchEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> SearchEngine:
    """Return the process-wide SearchEngine singleton."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = SearchEngine()
    return _engine


# ── API Handlers ──


def _confine_root(root_dir: str) -> str:
    """Return a resolved, allowlisted root_dir or raise ValueError.

    Search returns file contents by default, so root_dir must stay inside
    the project/data roots — an unconfined value would let API callers
    read arbitrary host files.
    """
    from l1.kernel.paths import get_paths

    _gp = get_paths()
    allowed = [Path(_gp.data_dir).resolve(), Path(_gp.config_dir).resolve()]
    with contextlib.suppress(OSError):
        allowed.append(Path.cwd().resolve())
    root = Path(root_dir).resolve()
    for base in allowed:
        try:
            root.relative_to(base)
            return str(root)
        except ValueError:
            continue
    raise ValueError(f"root_dir outside allowed search roots: {root_dir}")


def handle_search(body: dict | None = None) -> dict:
    """POST /api/search — unified search entry"""
    b = body or {}
    query = b.get("query", "")
    mode = b.get("mode", "auto")
    max_results = b.get("max_results", SEARCH_DEFAULT_RESULTS)
    if not query:
        return {"success": False, "error": "query required"}
    try:
        root = _confine_root(b.get("root", "."))
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return get_engine().search(query, mode=mode, root_dir=root, max_results=max_results)


def handle_search_semantic(body: dict | None = None) -> dict:
    """POST /api/search/semantic — semantic search"""
    b = body or {}
    query = b.get("query", "")
    pattern = b.get("pattern", "*.py")
    max_results = b.get("max_results", SEARCH_DEFAULT_RESULTS)
    if not query:
        return {"success": False, "error": "query required"}
    try:
        root = _confine_root(b.get("root", "."))
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return get_engine().semantic_search(query, root, pattern, max_results)


def handle_search_symbol(body: dict | None = None) -> dict:
    """POST /api/search/symbol — symbol search"""
    b = body or {}
    name = b.get("name", "")
    kind = b.get("kind", "")
    max_results = b.get("max_results", SYMBOL_SEARCH_RESULTS)
    if not name:
        return {"success": False, "error": "name required"}
    try:
        root = _confine_root(b.get("root", "."))
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return get_engine().symbol_search(name, kind, root, max_results)


def handle_search_docs(body: dict | None = None) -> dict:
    """POST /api/search/docs — API documentation search"""
    b = body or {}
    query = b.get("query", "")
    max_results = b.get("max_results", DOC_SEARCH_RESULTS)
    if not query:
        return {"success": False, "error": "query required"}
    return get_engine().doc_search(query, max_results)


def handle_search_index_doc(body: dict | None = None) -> dict:
    """POST /api/search/docs/index — register custom API documentation"""
    b = body or {}
    return get_engine().index_doc(
        package=b.get("package", ""),
        module=b.get("module", ""),
        name=b.get("name", ""),
        signature=b.get("signature", ""),
        docstring=b.get("docstring", ""),
        url=b.get("url", ""),
    )


# ── Route registration ──
# Routes are consolidated in l4/api/api_endpoints.py (ENDPOINT_MANIFEST); no duplicate list maintained here.
