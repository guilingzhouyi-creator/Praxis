"""2.1 Phase-1 tests — declarative diff-language registry (config-driven).

Verifies the language registry loads from config/discovery/diff_languages.yaml,
dispatches symbol extraction by declared backend, and falls back to
language-agnostic line-level diff for unlisted extensions — never hardcoded.
"""

from __future__ import annotations

import pytest

from l4.sandbox.diff_language import get_registry, reset_registry


@pytest.fixture(autouse=True)
def _clean():
    reset_registry()
    yield
    reset_registry()


def test_registry_declares_languages():
    """The registry exposes the languages declared in the YAML."""
    reg = get_registry()
    langs = reg.status()["languages"]
    assert "python" in langs
    assert "javascript" in langs
    assert "go" in langs
    assert "rust" in langs


def test_detect_language_by_extension():
    """Extension → language mapping comes from the registry, not code."""
    reg = get_registry()
    assert reg.detect_language("systems/python-reference-runtime/main.py") == "python"
    assert reg.detect_language("systems/typescript-shell-engine/app.ts") == "typescript"
    assert reg.detect_language("tests/fixtures/app.go") == "go"
    assert reg.detect_language("unknown.xyz") == ""  # unlisted → line-level


def test_semantic_gating_declared():
    """Semantic classification is declared per language (off for data files)."""
    reg = get_registry()
    assert reg.semantic_for("systems/python-reference-runtime/a.py") is True
    assert reg.semantic_for("systems/python-reference-runtime/b.json") is False
    assert reg.semantic_for("unknown.xyz") is False


def test_symbols_backend_python_ast(tmp_path):
    """python_ast backend extracts functions/classes/methods from .py files."""
    src = tmp_path / "sample.py"
    src.write_text("def alpha():\n    return 1\n\nclass Beta:\n    def method(self):\n        pass\n", encoding="utf-8")
    symbols = get_registry().symbols_for(str(src))
    names = {s["name"] for s in symbols}
    assert "alpha" in names
    assert "Beta" in names
    assert "method" in names


def test_symbols_backend_none_for_other_languages(tmp_path):
    """Languages with symbol_backend: none yield no symbols (declared)."""
    src = tmp_path / "app.go"
    src.write_text("package main\nfunc main() {}\n", encoding="utf-8")
    assert get_registry().symbols_for(str(src)) == []


def test_symbols_unlisted_extension_empty(tmp_path):
    """Unlisted extensions fall back to line-level (no symbols, no raise)."""
    src = tmp_path / "notes.txt"
    src.write_text("hello", encoding="utf-8")
    assert get_registry().symbols_for(str(src)) == []


def test_registry_missing_config_degrades(tmp_path):
    """A missing registry YAML loads an empty registry (never raises)."""
    from l4.sandbox.diff_language import DiffLanguageRegistry

    reg = DiffLanguageRegistry(config_path=str(tmp_path / "missing.yaml"))
    assert reg.status()["languages"] == []
    assert reg.detect_language("systems/python-reference-runtime/a.py") == ""
