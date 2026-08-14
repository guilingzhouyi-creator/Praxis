"""Doc-index consistency gate — every architecture doc must be linked from README.

AGENTS.md requires every new subsystem doc to be registered in BOTH this
index and the docs/architecture/README.md layer list. This machine gate proves
the README link surface covers every .md under docs/architecture/ (excluding
the generated llms files and README itself), so a new doc that skips
registration fails CI instead of silently going unindexed.

    python scripts/py/check_doc_index.py          # check only (CI gate)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ARCH = ROOT / "docs" / "architecture"
README = ARCH / "README.md"

# Files that are not "layer docs" and need no README link row.
_EXCLUDED = {"README.md", "llms.txt", "llms-full.txt"}


def index_docs() -> list[str]:
    """All .md layer docs under docs/architecture/ (excludes generated/index)."""
    return sorted(p.name for p in ARCH.glob("*.md") if p.name not in _EXCLUDED)


def check() -> list[str]:
    """Docs missing from the README link surface (empty = in sync)."""
    readme = README.read_text(encoding="utf-8")
    return [name for name in index_docs() if f"[{name}]" not in readme]


def main() -> int:
    missing = check()
    if not missing:
        print("Doc index is in sync: every architecture doc is linked from README.")
        return 0
    print("DRIFT: architecture docs not linked from docs/architecture/README.md:")
    for name in missing:
        print(f" - {name}")
    print("Add a link row (and the AGENTS.md index entry) for each, then re-run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
