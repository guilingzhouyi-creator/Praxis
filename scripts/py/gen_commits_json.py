#!/usr/bin/env python3
"""Regenerate config/discovery/commits.json from the commits.yaml source.

commits.yaml is the SINGLE SOURCE OF TRUTH for commit-message gates; the
Node.js commit-msg validation (scripts/js/validate-commit.mjs) reads
commits.json (JSON, no YAML dependency). Run this after editing
commits.yaml so the two never drift:

    python scripts/py/gen_commits_json.py

Writes only the keys the Node validator consumes; Python-side keys
(commit_scan extras such as branch_policy) stay in the YAML source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = ROOT / "config" / "discovery" / "commits.yaml"
JSON_PATH = ROOT / "config" / "discovery" / "commits.json"

# Keys consumed by scripts/js/validate-commit.mjs.
_NODE_KEYS = (
    "types",
    "non_imperative_verbs",
    "scope_dirs",
    "agents",
    "scopes",
    "placeholder",
    "max_subject_chars",
    "body",
    "strictness",
    "type_content_rules",
)


def main() -> int:
    """Regenerate the Node policy mirror from the YAML source."""
    with YAML_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    payload = {k: data[k] for k in _NODE_KEYS if k in data}
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    JSON_PATH.write_text(text, encoding="utf-8")
    print(f"commits.json regenerated from commits.yaml ({len(payload)} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
