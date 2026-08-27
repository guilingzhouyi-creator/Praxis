"""Search engine — semantic (TF-IDF keyword) backend.

Extracted from ``search_engine.py``: lightweight keyword search with
TF-IDF weighting, no external dependencies.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from l1.kernel.params.system import SEARCH_DEFAULT_RESULTS

from .search_models import SearchResult, is_ignored_path

logger = logging.getLogger(__name__)


class SemanticSearch:
    """Lightweight semantic search — TF-IDF keyword ranking, no external dependencies."""

    def __init__(self):
        self._lock = threading.Lock()

    def search(
        self,
        query: str,
        root_dir: str = ".",
        file_pattern: str = "*.py",
        max_results: int = SEARCH_DEFAULT_RESULTS,
        include_content: bool = True,
    ) -> dict:
        """Search code content by keyword, ranked by TF-IDF."""
        root = Path(root_dir).resolve()
        if not root.exists():
            return {"success": False, "error": f"directory not found: {root_dir}"}

        query_terms = query.lower().split()
        if not query_terms:
            return {"success": False, "error": "empty query"}

        # 1. Collect matching files
        matches: list[SearchResult] = []
        files = list(root.rglob(file_pattern))

        for file_path in files:
            if is_ignored_path(file_path):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                for i, line in enumerate(lines, 1):
                    line_lower = line.lower()
                    # Compute TF-IDF score
                    score: float = sum(1 for t in query_terms if t in line_lower)
                    if score > 0:
                        # IDF weighting: rare terms get higher weight
                        idf_score = sum(
                            1.0 / (1.0 + self._term_frequency(t, content)) for t in query_terms if t in line_lower
                        )
                        score = score * idf_score
                        matches.append(
                            SearchResult(
                                path=str(file_path.relative_to(root)),
                                line=i,
                                content=line.strip() if include_content else "",
                                score=score,
                                kind="text",
                            )
                        )
            except Exception:
                continue

        # 2. Sort by score descending
        matches.sort(key=lambda r: -r.score)
        results = matches[:max_results]

        return {
            "success": True,
            "query": query,
            "total_matches": len(matches),
            "results": [r.to_dict() for r in results],
            "truncated": len(matches) > max_results,
        }

    def _term_frequency(self, term: str, content: str) -> float:
        return content.lower().count(term) / max(len(content), 1)
