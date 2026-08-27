"""Run mypy against the Python reference tree through a valid package alias.

The runtime directory intentionally uses a kebab-case system identity
(``python-reference-runtime``). Mypy treats a directory containing
``__init__.py`` as a package root and rejects that identity before checking
any source. A temporary underscore alias preserves the exact source tree and
lets the type checker inspect it without weakening the naming boundary.

    python scripts/py/run_mypy.py --no-namespace-packages
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "systems" / "python-reference-runtime"
ALIAS_NAME = "python_reference_runtime"


def main() -> int:
    """Run mypy with a temporary valid package-name alias."""
    executable = shutil.which("mypy")
    if executable is None:
        print("mypy not installed — type check cannot run", file=sys.stderr)
        return 127
    if not SOURCE_ROOT.is_dir():
        print(f"missing mypy source root: {SOURCE_ROOT}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="praxis-mypy-") as temp_root:
        alias = Path(temp_root) / ALIAS_NAME
        alias.symlink_to(SOURCE_ROOT, target_is_directory=True)
        command = [executable, str(alias), *sys.argv[1:]]
        return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
