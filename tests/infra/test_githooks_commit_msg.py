"""Tests for .githooks/commit-msg — the commit governance gate.

Drives the bash hook with synthetic commit messages and asserts its exit code,
so the rules (English, Co-Authored-By, Conventional-Commits type, Merge
exemption) are machine-verified rather than trusted by convention.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".githooks" / "commit-msg"

COAUTH = "Co-Authored-By: Test Agent <test@example.org>"


def run_hook(message: str) -> int:
    """Run the commit-msg hook against a message, returning its exit code."""
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(message)
        path = f.name
    try:
        result = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True)
        return result.returncode
    finally:
        Path(path).unlink(missing_ok=True)


def test_valid_conventional_passes():
    assert run_hook(f"feat(core): add token ring revocation\n\n{COAUTH}\n") == 0


def test_missing_coauth_rejected():
    assert run_hook("feat(core): add token ring revocation\n") == 1


def test_cjk_subject_rejected():
    assert run_hook(f"feat: 中文摘要\n\n{COAUTH}\n") == 1


def test_non_conventional_subject_rejected():
    assert run_hook(f"Update readme\n\n{COAUTH}\n") == 1


def test_unknown_type_rejected():
    assert run_hook(f"foobar(core): something\n\n{COAUTH}\n") == 1


def test_merge_message_exempt():
    # Merge subjects skip the English/CoAuth/type checks (git-generated).
    assert run_hook("Merge branch 'feature/x'\n") == 0
