"""Search engine — API documentation backend.

Extracted from ``search_engine.py``: doc entry search over a built-in
stdlib reference index plus a dynamically extensible custom index.
"""

from __future__ import annotations

from l1.kernel.params.system import (
    DOC_SEARCH_RESULTS,
    SEARCH_SCORE_DOCSTRING_MATCH,
    SEARCH_SCORE_FULL_MATCH,
    SEARCH_SCORE_MODULE_MATCH,
    SEARCH_SCORE_NAME_MATCH,
    SEARCH_SCORE_PACKAGE_MATCH,
)

from .search_models import DocEntry


class DocSearch:
    """API documentation search — built-in index + dynamic extension."""

    # Fast reference index for common Python stdlib modules
    STDLIB_INDEX: dict[str, DocEntry] = {
        "pathlib.Path": DocEntry(
            "stdlib",
            "pathlib",
            "Path",
            "Path(*pathsegments)",
            "PurePath subclass for concrete paths.",
            "https://docs.python.org/3/library/pathlib.html",
        ),
        "os.path.join": DocEntry(
            "stdlib",
            "os.path",
            "join",
            "os.path.join(path, *paths)",
            "Join path segments intelligently.",
            "https://docs.python.org/3/library/os.path.html",
        ),
        "json.dumps": DocEntry(
            "stdlib",
            "json",
            "dumps",
            "json.dumps(obj, *, ...)",
            "Serialize object to JSON string.",
            "https://docs.python.org/3/library/json.html",
        ),
        "json.loads": DocEntry(
            "stdlib",
            "json",
            "loads",
            "json.loads(s, *, ...)",
            "Deserialize JSON string to object.",
            "https://docs.python.org/3/library/json.html",
        ),
        "re.search": DocEntry(
            "stdlib",
            "re",
            "search",
            "re.search(pattern, string, flags=0)",
            "Search string for match to pattern.",
            "https://docs.python.org/3/library/re.html",
        ),
        "subprocess.run": DocEntry(
            "stdlib",
            "subprocess",
            "run",
            "subprocess.run(args, *, ...)",
            "Run command with arguments.",
            "https://docs.python.org/3/library/subprocess.html",
        ),
        "threading.Thread": DocEntry(
            "stdlib",
            "threading",
            "Thread",
            "Thread(target=None, ...)",
            "Create a new thread.",
            "https://docs.python.org/3/library/threading.html",
        ),
        "dataclasses.dataclass": DocEntry(
            "stdlib",
            "dataclasses",
            "dataclass",
            "@dataclass(*, ...)",
            "Decorator for data class.",
            "https://docs.python.org/3/library/dataclasses.html",
        ),
        "logging.getLogger": DocEntry(
            "stdlib",
            "logging",
            "getLogger",
            "logging.getLogger(name=None)",
            "Return a logger with the given name.",
            "https://docs.python.org/3/library/logging.html",
        ),
        "pathlib.Path.read_text": DocEntry(
            "stdlib",
            "pathlib",
            "Path.read_text",
            "Path.read_text(encoding=None, ...)",
            "Read file contents as string.",
            "https://docs.python.org/3/library/pathlib.html",
        ),
        "pathlib.Path.write_text": DocEntry(
            "stdlib",
            "pathlib",
            "Path.write_text",
            "Path.write_text(data, encoding=None, ...)",
            "Write string to file.",
            "https://docs.python.org/3/library/pathlib.html",
        ),
        "hashlib.sha256": DocEntry(
            "stdlib",
            "hashlib",
            "sha256",
            "hashlib.sha256(data=b'', ...)",
            "Return SHA-256 hash object.",
            "https://docs.python.org/3/library/hashlib.html",
        ),
        "os.environ.get": DocEntry(
            "stdlib",
            "os",
            "environ.get",
            "os.environ.get(key, default=None)",
            "Get environment variable.",
            "https://docs.python.org/3/library/os.html",
        ),
    }

    def __init__(self):
        self._custom_index: dict[str, DocEntry] = {}

    def search(self, query: str, max_results: int = DOC_SEARCH_RESULTS) -> dict:
        """Search API documentation."""
        q = query.lower()
        results: list[DocEntry] = []

        # Search built-in index
        all_entries = dict(self.STDLIB_INDEX)
        all_entries.update(self._custom_index)

        for key, entry in all_entries.items():
            score = 0
            if q in key.lower():
                score += SEARCH_SCORE_FULL_MATCH
            if q in entry.name.lower():
                score += SEARCH_SCORE_NAME_MATCH
            if q in entry.docstring.lower():
                score += SEARCH_SCORE_DOCSTRING_MATCH
            if q in entry.module.lower():
                score += SEARCH_SCORE_MODULE_MATCH
            if q in entry.package.lower():
                score += SEARCH_SCORE_PACKAGE_MATCH
            if score > 0:
                results.append(entry)

        # Sort by score
        results.sort(key=lambda e: -self._rank(e, q))
        top = results[:max_results]

        return {
            "success": True,
            "query": query,
            "total": len(results),
            "results": [e.to_dict() for e in top],
        }

    def _rank(self, entry: DocEntry, query: str) -> float:
        score = 0
        full = f"{entry.package}.{entry.module}.{entry.name}".lower()
        if query in full:
            score += SEARCH_SCORE_FULL_MATCH
        if query in entry.name.lower():
            score += SEARCH_SCORE_NAME_MATCH
        if query in entry.docstring.lower():
            score += SEARCH_SCORE_DOCSTRING_MATCH
        return score

    def index(
        self, package: str, module: str, name: str, signature: str = "", docstring: str = "", url: str = ""
    ) -> dict:
        """Register a custom API documentation entry."""
        key = f"{package}.{module}.{name}"
        self._custom_index[key] = DocEntry(
            package=package,
            module=module,
            name=name,
            signature=signature,
            docstring=docstring,
            url=url,
        )
        return {"success": True, "key": key}
