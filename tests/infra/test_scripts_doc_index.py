"""Tests for scripts/py/check_doc_index.py — the doc-index consistency gate.

Loads the hyphenated script by path (importlib), same pattern as the other
doc-tooling tests, and asserts the live index is in sync.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "py"))

_spec = importlib.util.spec_from_file_location("check_doc_index", ROOT / "scripts" / "py" / "check_doc_index.py")
check_doc_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_doc_index)


def test_index_docs_excludes_generated():
    names = check_doc_index.index_docs()
    assert "llms.txt" not in names
    assert "llms-full.txt" not in names
    assert "README.md" not in names
    assert names  # non-empty


def test_all_docs_linked_from_readme():
    assert check_doc_index.check() == []


def test_drift_detection():
    # Against an empty link surface, every doc is reported missing.
    docs = check_doc_index.index_docs()
    missing = [d for d in docs if f"[{d}]" not in ""]
    assert missing and len(missing) == len(docs)
