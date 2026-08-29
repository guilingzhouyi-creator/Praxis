"""Regression tests for the outgoing pre-storage archival pipeline (doc_archive.py).

Covers the two contract violations found by review:
- the first ROADMAP archival must not collide with the still-active
  ROADMAP-2026-长期-001..011 series (fondss-wide sequence scan);
- a batch of same-fonds outgoing docs archived in one commit must receive
  distinct archive numbers (per-fonds pre-allocated sequence).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "py"))  # noqa: E402
import doc_archive  # noqa: E402

ROADMAP_ACTIVE = [
    {
        "pointer": f"ROADMAP-2026-08-15-{i:03d}",
        "archive_number": f"ROADMAP-2026-长期-{i:03d}",
        "fonds": "ROADMAP",
        "status": "active",
    }
    for i in range(1, 12)
]
DESIGN_ARCHIVED = [
    {
        "pointer": f"ARCH-DESIGN-2026-08-16-{i:03d}",
        "archive_number": f"DESIGN-2026-永久-{i:03d}",
        "fonds": "DESIGN",
        "status": "archived",
    }
    for i in range(1, 23)
]


def _patch_module(monkeypatch, tmp_path: Path) -> None:
    """Point doc_archive's file-system constants at the test sandbox."""
    monkeypatch.setattr(doc_archive, "ROOT", tmp_path)
    monkeypatch.setattr(doc_archive, "POINTERS_JSON", tmp_path / "docs/design/POINTERS.json")
    monkeypatch.setattr(doc_archive, "ARCHIVE", tmp_path / "docs/design/archive")
    monkeypatch.setattr(
        doc_archive,
        "FONDS_ARCHIVE",
        {
            "DESIGN": {
                "dir": tmp_path / "docs/design/archive/001-design/2026/永久",
                "retention": "永久",
                "prefix": "ARCH-DESIGN",
            },
            "ROADMAP": {
                "dir": tmp_path / "docs/design/archive/003-roadmap/2026/长期",
                "retention": "长期",
                "prefix": "ARCH-ROADMAP",
            },
        },
    )
    monkeypatch.setattr(doc_archive, "_run", lambda _cmd: True)


def _write_pointers(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "docs/design/POINTERS.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _write_outgoing(tmp_path: Path, name: str, fonds: str = "ROADMAP", construction: str = "closed") -> Path:
    p = tmp_path / "docs/design/_outgoing" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"""---
pointer: {fonds}-2026-08-23-010
archive_number: {fonds}-2026-长期-010
fonds: {fonds}
year: 2026
retention: 长期
title: "Test doc"
author: L3
formation_date: 2026-08-23
carrier: md
classification: 内部
pages: 3
archivist: L3
reviewer: L3
archive_date: 2026-08-29
source: {fonds.lower()}
keywords: []
abstract: "Test doc for doc_archive regression."
series: active
date: 2026-08-23
status: active
construction: {construction}
---

# Test doc
""",
        encoding="utf-8",
    )
    return p


def test_first_roadmap_archive_skips_active_series(monkeypatch, tmp_path) -> None:
    """First ROADMAP archival must derive seq 012, past the active 001-011 series."""
    _patch_module(monkeypatch, tmp_path)
    _write_pointers(tmp_path, ROADMAP_ACTIVE + DESIGN_ARCHIVED)
    src = _write_outgoing(tmp_path, "roadmap-x.md")

    target, err = doc_archive.archive_file(src)

    assert err is None
    assert target is not None
    assert "ROADMAP-2026-长期-012_" in target
    fm = (tmp_path / target).read_text(encoding="utf-8").split("---", 2)[1]
    assert "pointer: ARCH-ROADMAP-2026-08-29-012" in fm
    assert "archive_number: ROADMAP-2026-长期-012" in fm
    assert "status: archived" in fm
    assert "original_name: roadmap-x.md" in fm
    assert not src.exists()


def test_batch_archival_gets_unique_archive_numbers(monkeypatch, tmp_path) -> None:
    """Two same-fonds docs archived in one batch must not share an archive number."""
    _patch_module(monkeypatch, tmp_path)
    _write_pointers(tmp_path, ROADMAP_ACTIVE + DESIGN_ARCHIVED)
    _write_outgoing(tmp_path, "roadmap-a.md")
    _write_outgoing(tmp_path, "roadmap-b.md")

    rc = doc_archive._archive_batch(["docs/design/_outgoing/roadmap-a.md", "docs/design/_outgoing/roadmap-b.md"])

    assert rc == 0
    archived_dir = tmp_path / "docs/design/archive/003-roadmap/2026/长期"
    nums = sorted(p.name.split("_")[0] for p in archived_dir.glob("*.md"))
    assert nums == ["ROADMAP-2026-长期-012", "ROADMAP-2026-长期-013"]


def test_auto_seq_skips_occupied_archive_number(monkeypatch, tmp_path) -> None:
    """The collision guard must skip an archive number that already exists."""
    _patch_module(monkeypatch, tmp_path)
    entries = ROADMAP_ACTIVE + [
        {
            "pointer": "ARCH-ROADMAP-2026-08-29-012",
            "archive_number": "ROADMAP-2026-长期-012",
            "fonds": "ROADMAP",
            "status": "archived",
        }
    ]
    _write_pointers(tmp_path, entries)
    src = _write_outgoing(tmp_path, "roadmap-x.md")

    target, err = doc_archive.archive_file(src)

    assert err is None
    assert "ROADMAP-2026-长期-013_" in target


def test_validation_rejects_non_closed_doc(monkeypatch, tmp_path) -> None:
    """A doc without construction: closed must not be archived."""
    _patch_module(monkeypatch, tmp_path)
    _write_pointers(tmp_path, ROADMAP_ACTIVE)
    src = _write_outgoing(tmp_path, "roadmap-x.md", construction="in_progress")

    target, err = doc_archive.archive_file(src)

    assert target is None
    assert err is not None
    assert "construction must be 'closed'" in err
    assert src.exists()
