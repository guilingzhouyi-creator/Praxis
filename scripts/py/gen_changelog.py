#!/usr/bin/env python3
"""Generate the [Unreleased] section of CHANGELOG.md — thin CLI wrapper.

All logic lives in ``_lib/changelog_render.py`` (scan/group/render); this
wrapper only preserves a stable command surface for ``make changelog`` and
CI gates.

    python scripts/py/gen_changelog.py            # update [Unreleased]
    python scripts/py/gen_changelog.py --dry-run  # preview, write nothing
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

_spec = importlib.util.spec_from_file_location(
    "changelog_render", ROOT / "scripts" / "py" / "_lib" / "changelog_render.py"
)
if _spec is None or _spec.loader is None:
    raise ImportError("cannot load scripts/py/_lib/changelog_render.py")
changelog_render = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(changelog_render)

if __name__ == "__main__":
    sys.exit(changelog_render.main())
