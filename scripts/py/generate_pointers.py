#!/usr/bin/env python3
"""Regenerate POINTERS.json and POINTERS.db from current files."""

import json
import pathlib
import re
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
POINTERS_JSON = ROOT / "docs/design/POINTERS.json"
POINTERS_DB = ROOT / "docs/design/POINTERS.db"
ARCHIVE = ROOT / "docs/design/archive"


def extract(p: pathlib.Path):
    txt = p.read_text(encoding="utf-8", errors="ignore")

    def get(k):
        m = re.search(rf"^{k}:\s*(.+)$", txt, re.M)
        return m.group(1).strip().strip('"') if m else ""

    return {
        "pointer": get("pointer"),
        "archive_number": get("archive_number"),
        "fonds": get("fonds"),
        "year": get("year"),
        "retention": get("retention"),
        "title": get("title"),
        "author": get("author"),
        "formation_date": get("formation_date"),
        "carrier": get("carrier"),
        "classification": get("classification"),
        "pages": get("pages"),
        "archivist": get("archivist"),
        "reviewer": get("reviewer"),
        "archive_date": get("archive_date"),
        "source": get("source"),
        "keywords": get("keywords"),
        "abstract": get("abstract"),
        "file": "",
        "type": "",
        "status": "",
    }


index = []
active_dir = ROOT / "docs/design"
for p in sorted(active_dir.glob("*.md")):
    if p.name in ["README.md", "archive-spec.md"]:
        continue
    if "_incoming" in str(p):
        continue
    fields = extract(p)
    if not fields["pointer"]:
        continue
    fields["file"] = p.name
    fields["type"] = "design-active"
    fields["status"] = "active"
    index.append(fields)

for p in sorted((ARCHIVE / "001-design").rglob("*.md")) if (ARCHIVE / "001-design").exists() else []:
    fields = extract(p)
    if not fields["pointer"]:
        continue
    rel = p.relative_to(ARCHIVE).as_posix()
    fields["file"] = f"archive/{rel}"
    fields["type"] = "design"
    fields["status"] = "archived"
    index.append(fields)

for p in sorted((ARCHIVE / "002-review").rglob("*.md")) if (ARCHIVE / "002-review").exists() else []:
    if p.name == "README.md":
        continue
    fields = extract(p)
    if not fields["pointer"]:
        continue
    rel = p.relative_to(ARCHIVE).as_posix()
    fields["file"] = f"archive/{rel}"
    fields["type"] = "review"
    fields["status"] = "archived"
    index.append(fields)

index_sorted = sorted(index, key=lambda x: x["pointer"])
POINTERS_JSON.write_text(json.dumps(index_sorted, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {POINTERS_JSON} with {len(index_sorted)}")

# SQLite
if POINTERS_DB.exists():
    POINTERS_DB.unlink()
conn = sqlite3.connect(str(POINTERS_DB))
conn.execute("""CREATE TABLE pointers (
    pointer TEXT PRIMARY KEY,
    archive_number TEXT,
    fonds TEXT,
    year TEXT,
    retention TEXT,
    title TEXT,
    author TEXT,
    formation_date TEXT,
    carrier TEXT,
    classification TEXT,
    pages INTEGER,
    file TEXT,
    type TEXT,
    status TEXT,
    keywords TEXT,
    abstract TEXT
)""")
conn.execute("CREATE INDEX idx_fonds_year ON pointers(fonds, year)")
conn.execute("CREATE INDEX idx_title ON pointers(title)")
for e in index_sorted:
    try:
        pages = int(e["pages"]) if str(e["pages"]).isdigit() else 0
    except Exception:
        pages = 0
    conn.execute(
        "INSERT INTO pointers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            e["pointer"],
            e["archive_number"],
            e["fonds"],
            e["year"],
            e["retention"],
            e["title"],
            e["author"],
            e["formation_date"],
            e["carrier"],
            e["classification"],
            pages,
            e["file"],
            e["type"],
            e["status"],
            e["keywords"],
            e["abstract"],
        ),
    )
conn.commit()
conn.close()
print(f"Created {POINTERS_DB} ({POINTERS_DB.stat().st_size} bytes)")
