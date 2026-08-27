"""API diff handlers — structured diff, history, colors."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))


class TestDiffHandlers:
    def test_diff_structured_importable(self):
        from l4.api.api_handlers_diff import diff_structured

        assert callable(diff_structured)

    def test_diff_history_importable(self):
        from l4.api.api_handlers_diff import diff_history

        assert callable(diff_history)

    def test_diff_colors_importable(self):
        from l4.api.api_handlers_diff import diff_colors

        assert callable(diff_colors)


class TestDiffReviewContext:
    """2.1 — review tier attaches LSP diagnostics + AST symbols as context."""

    def test_lsp_diagnostics_empty_without_path(self):
        from l4.api.api_handlers_diff import _lsp_diagnostics

        assert _lsp_diagnostics("") == []

    def test_lsp_diagnostics_degrades(self, monkeypatch):
        from l4.api.api_handlers_diff import _lsp_diagnostics

        def _boom(_):
            raise RuntimeError("lsp unavailable")

        monkeypatch.setattr("l4.lsp.lsp_manager.get_manager", _boom)
        assert _lsp_diagnostics("systems/python-reference-runtime/a.py") == []

    def test_ast_symbols_empty_without_path(self):
        from l4.api.api_handlers_diff import _ast_symbols

        assert _ast_symbols("") == []

    def test_ast_symbols_extract_from_python_file(self, tmp_path):
        from l4.api.api_handlers_diff import _ast_symbols

        src = tmp_path / "sample_mod.py"
        src.write_text("def alpha():\n    return 1\n\nclass Beta:\n    pass\n", encoding="utf-8")
        syms = _ast_symbols(str(src))
        names = {s["name"] for s in syms}
        assert "alpha" in names
        assert "Beta" in names

    def test_review_tier_attaches_context(self, monkeypatch):
        from l4.api import api_handlers_diff as m

        monkeypatch.setattr(m, "_is_enabled", lambda: True)
        monkeypatch.setattr(m, "_lsp_diagnostics", lambda p: [{"severity": "error", "message": "x"}])
        monkeypatch.setattr(m, "_ast_symbols", lambda p: [{"name": "alpha", "type": "function", "line": 1}])
        r = m.diff_tier(
            {
                "tier": "review",
                "old_text": "def a():\n    pass\n",
                "new_text": "def a():\n    return 1\n",
                "rel_path": "systems/python-reference-runtime/x.py",
                "agent_id": "rev-1",
            }
        )
        assert r["success"] is True
        assert r["diff"]["lsp_diagnostics"] == [{"severity": "error", "message": "x"}]
        assert r["diff"]["ast_symbols"] == [{"name": "alpha", "type": "function", "line": 1}]


class TestDiffReviewAstFrame:
    """2.1 Phase 3 — review tier attaches an AST tree-edit frame for python."""

    def test_review_python_attaches_ast_frame(self, monkeypatch):
        from l4.api import api_handlers_diff as m

        monkeypatch.setattr(m, "_is_enabled", lambda: True)
        monkeypatch.setattr(m, "_lsp_diagnostics", lambda p: [])
        monkeypatch.setattr(m, "_ast_symbols", lambda p: [])
        r = m.diff_tier(
            {
                "tier": "review",
                "old_text": "def foo(a):\n    return a + 1\n",
                "new_text": "def foo(a):\n    return a + 2\n",
                "rel_path": "systems/python-reference-runtime/x.py",
                "agent_id": "rev-1",
            }
        )
        assert r["success"] is True
        diff = r["diff"]
        assert "ast_frame" in diff
        assert diff["ast_frame"][8:11] == b"PDA"
        assert diff["ast_frame_header"]["frame_type"] == 2
        # The AST frame decodes back to a replayable script.
        from l4.sandbox.diff_codec import decode_ast_script

        script = decode_ast_script(diff["ast_frame"])
        assert script is not None

    def test_review_non_python_no_ast_frame(self, monkeypatch):
        from l4.api import api_handlers_diff as m

        monkeypatch.setattr(m, "_is_enabled", lambda: True)
        monkeypatch.setattr(m, "_lsp_diagnostics", lambda p: [])
        monkeypatch.setattr(m, "_ast_symbols", lambda p: [])
        r = m.diff_tier(
            {
                "tier": "review",
                "old_text": "package main\nfunc main() {}\n",
                "new_text": "package main\nfunc main() { x := 1 }\n",
                "rel_path": "tests/fixtures/app.go",
                "agent_id": "rev-1",
            }
        )
        assert r["success"] is True
        # Go declares tree_backend: none → hunk frame only, no AST frame.
        assert "ast_frame" not in r["diff"]

    def test_review_unparseable_python_falls_back(self, monkeypatch):
        """Syntax-invalid python keeps the hunk frame (declarative fallback)."""
        from l4.api import api_handlers_diff as m

        monkeypatch.setattr(m, "_is_enabled", lambda: True)
        monkeypatch.setattr(m, "_lsp_diagnostics", lambda p: [])
        monkeypatch.setattr(m, "_ast_symbols", lambda p: [])
        r = m.diff_tier(
            {
                "tier": "review",
                "old_text": "def broken(:",
                "new_text": "def broken(:\n    pass\n",
                "rel_path": "systems/python-reference-runtime/broken.py",
                "agent_id": "rev-1",
            }
        )
        assert r["success"] is True
        assert "ast_frame" not in r["diff"]  # unparseable → no AST frame
        assert "frame" in r["diff"]  # hunk frame still present
