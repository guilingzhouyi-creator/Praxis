#!/usr/bin/env python3
"""Regenerate the Node commit-policy mirror from the YAML source."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = ROOT / "config" / "discovery" / "commits.yaml"
JSON_PATH = ROOT / "config" / "discovery" / "commits.json"

_NODE_KEYS = (
    "types",
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
    """Write the JSON keys consumed by the Node commit hook."""
    with YAML_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    payload = {key: data[key] for key in _NODE_KEYS if key in data}
    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"commits.json regenerated from commits.yaml ({len(payload)} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
