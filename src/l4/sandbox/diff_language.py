"""Declarative diff-language registry (2.1) — config-driven, never hardcoded.

Languages are declared in ``config/discovery/diff_languages.yaml`` (auto-
discovered at boot by ConfigDiscovery). This module loads that registry and
dispatches language-specific diff behavior:

  - ``symbols_for``      — AST symbol extraction backend per language
  - ``semantic_for``     — whether hunk semantic classification applies
  - ``detect_language``  — extension → language mapping

Any unlisted extension falls back to a language-agnostic line-level diff
(no symbol extraction, no semantic labels) — never a hard error, so adding
a new language is a YAML edit, not a code change.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Backends: name → symbol extractor factory. The python_ast backend uses the
# stdlib ast; all other languages declare "none" (line-level only) until a
# backend is implemented — declared, not hardcoded per language.
_BACKENDS: dict[str, Callable[[str], list[dict[str, Any]]]] = {}


def _python_ast_symbols(file_path: str) -> list[dict[str, Any]]:
    """Extract top-level functions/classes/methods via the stdlib ``ast``."""
    try:
        from l4.search.search_engine import SymbolSearch

        r = SymbolSearch().symbols_in_file(file_path)
        return r.get("symbols", []) if r.get("success") else []
    except Exception as e:
        logger.debug("diff_language: python ast symbols skipped: %s", e)
        return []


def register_backend(name: str, fn: Callable[[str], list[dict[str, Any]]]) -> None:
    """Register a symbol-extraction backend (extensible, code-registered)."""
    _BACKENDS[name] = fn


register_backend("python_ast", _python_ast_symbols)


class DiffLanguageRegistry:
    """Registry loaded from config/discovery/diff_languages.yaml."""

    def __init__(self, config_path: str = "") -> None:
        self._lock = threading.RLock()
        self._languages: dict[str, dict[str, Any]] = {}
        self._config_path = config_path or self._default_path()
        self._load()

    @staticmethod
    def _default_path() -> str:
        """Resolve the registry YAML from the repo config/discovery dir.

        Mirrors department.py's loader: resolve from the module location
        (src/l4/sandbox → repo root) so CLI_PROJECT mode finds
        ``config/discovery/diff_languages.yaml`` regardless of the runtime
        data/config dir. Falls back to a relative path when missing.
        """
        try:
            p = Path(__file__).resolve().parent.parent.parent.parent / "config" / "discovery" / "diff_languages.yaml"
            if p.exists():
                return str(p)
        except Exception as e:
            logger.debug("diff_language: config path resolve skipped: %s", e)
        return "config/discovery/diff_languages.yaml"

    def _load(self) -> None:
        """Load and validate the declarative language registry (never raises)."""
        try:
            import yaml

            p = Path(self._config_path)
            if not p.exists():
                logger.warning("diff_language: registry missing at %s", p)
                return
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for lang, spec in (data.get("diff_languages") or {}).items():
                if not isinstance(spec, dict):
                    continue
                self._languages[str(lang)] = {
                    "extensions": [str(e) for e in (spec.get("extensions") or [])],
                    "symbol_backend": str(spec.get("symbol_backend", "none")),
                    "tree_backend": str(spec.get("tree_backend", "none")),
                    "semantic": bool(spec.get("semantic", True)),
                }
        except Exception as e:
            logger.warning("diff_language: registry load failed: %s", e)

    def detect_language(self, file_path: str) -> str:
        """Map a file extension to its declared language ('' when unlisted)."""
        ext = Path(file_path).suffix.lower()
        with self._lock:
            for lang, spec in self._languages.items():
                if ext in spec["extensions"]:
                    return lang
        return ""

    def semantic_for(self, file_path: str) -> bool:
        """Whether hunk semantic classification applies to this file."""
        lang = self.detect_language(file_path)
        if not lang:
            return False
        with self._lock:
            return bool(self._languages[lang].get("semantic"))

    def symbols_for(self, file_path: str) -> list[dict[str, Any]]:
        """Extract AST symbols for a file via its declared backend.

        Unlisted languages return [] (line-level diff only). Backends
        degrade gracefully (never raise).
        """
        lang = self.detect_language(file_path)
        if not lang:
            return []
        with self._lock:
            backend = self._languages[lang].get("symbol_backend", "none")
        fn = _BACKENDS.get(backend)
        if fn is None:
            return []
        try:
            return fn(file_path)
        except Exception as e:
            logger.debug("diff_language: symbols backend skipped: %s", e)
            return []

    def status(self) -> dict:
        """Registry status (declared languages + backends)."""
        with self._lock:
            return {
                "languages": sorted(self._languages.keys()),
                "backends": sorted(_BACKENDS.keys()),
                "config": self._config_path,
            }


# ── Singleton ──────────────────────────────────────────────────────────

_registry: DiffLanguageRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> DiffLanguageRegistry:
    """Get the shared DiffLanguageRegistry singleton (lazy init)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = DiffLanguageRegistry()
    return _registry


def reset_registry() -> None:
    """Drop the singleton (used by tests)."""
    global _registry
    with _registry_lock:
        _registry = None
