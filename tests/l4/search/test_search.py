"""Search service tests — search and replace functions."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))


class TestSearch:
    def test_search_importable(self):
        from l4.search.search import search

        assert callable(search)

    def test_replace_importable(self):
        from l4.search.search import replace

        assert callable(replace)


class TestSymbolsInFile:
    """2.1 — SymbolSearch.symbols_in_file extracts AST symbols for review context."""

    def test_symbols_in_file_python(self, tmp_path):
        from l4.search.search_engine import SymbolSearch

        src = tmp_path / "sample_mod.py"
        src.write_text(
            "def alpha():\n    return 1\n\nclass Beta:\n    def method(self):\n        pass\n", encoding="utf-8"
        )
        r = SymbolSearch().symbols_in_file(str(src))
        assert r["success"] is True
        names = {s["name"] for s in r["symbols"]}
        types = {s["name"]: s["type"] for s in r["symbols"]}
        assert "alpha" in names and types["alpha"] == "function"
        assert "Beta" in names and types["Beta"] == "class"
        assert "method" in names and types["method"] == "method"

    def test_symbols_in_file_missing(self):
        from l4.search.search_engine import SymbolSearch

        r = SymbolSearch().symbols_in_file("does-not-exist.py")
        assert r["success"] is False
        assert r["symbols"] == []

    def test_symbols_in_file_non_python(self, tmp_path):
        from l4.search.search_engine import SymbolSearch

        src = tmp_path / "notes.txt"
        src.write_text("hello", encoding="utf-8")
        r = SymbolSearch().symbols_in_file(str(src))
        assert r["success"] is False
