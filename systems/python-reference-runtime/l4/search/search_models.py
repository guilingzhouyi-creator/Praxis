"""Search engine — shared data models.

Extracted from ``search_engine.py``: the SearchResult / DocEntry records
and the shared ignore-path helper used by the semantic and symbol
backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from l1.kernel.params.system import LOG_TRUNC_100, LOG_TRUNC_200


@dataclass
class SearchResult:
    """A single search result."""

    path: str
    line: int = 0
    column: int = 0
    content: str = ""
    score: float = 0.0
    kind: str = "text"  # text | symbol | doc
    symbol_name: str = ""  # symbol name (when symbol search)
    symbol_type: str = ""  # function | class | variable | method

    def to_dict(self) -> dict:
        """Convert the search result to a serializable dict."""
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "content": self.content[:LOG_TRUNC_200],
            "score": round(self.score, 3),
            "kind": self.kind,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
        }


@dataclass
class DocEntry:
    """An API documentation entry."""

    package: str
    module: str
    name: str
    signature: str = ""
    docstring: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        """Convert the doc entry to a serializable dict."""
        return {
            "package": self.package,
            "module": self.module,
            "name": self.name,
            "signature": self.signature[:LOG_TRUNC_100],
            "docstring": self.docstring[:LOG_TRUNC_200],
            "url": self.url,
        }


_IGNORED_PARTS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".egg-info"}


def is_ignored_path(path: Path) -> bool:
    """Skip .git, node_modules, __pycache__, .venv, etc."""
    return any(p in _IGNORED_PARTS for p in path.parts)
