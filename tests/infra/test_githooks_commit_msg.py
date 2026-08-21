"""Tests for .githooks/commit-msg — the commit governance gate.

Drives the bash hook with synthetic commit messages and asserts its exit code,
so the rules (English, Co-Authored-By, Conventional-Commits type, Merge
exemption) are machine-verified rather than trusted by convention.

Attribution-dependent tests (``test_valid_conventional_passes``) require a
live harness session log (``detect_agent.py`` evidence A or B). In a plain
shell the hook rejects because the model cannot be verified by execution
evidence — the test then skips gracefully.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".githooks" / "commit-msg"

COAUTH = "Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"


def _attribution_available() -> bool:
    """Check whether the hook can verify attribution (harness session log).

    In a harness session (DSH/CI) ``detect_agent.py`` reads the session log
    and returns high-confidence evidence (A=execution log, B=process chain).
    In a plain shell only config-based evidence (C) is available, and the hook
    rejects attribution.
    """
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts/py/detect_agent.py"), "--json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(r.stdout)
        return data.get("evidence") in ("A", "B")
    except Exception:
        return False


def run_hook(message: str) -> int:
    """Run the commit-msg hook against a message, returning its exit code."""
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(message)
        path = f.name
    try:
        env = os.environ.copy()
        env.update(
            {
                "PRAXIS_AUTHOR": "AtomCode",
                "PRAXIS_MODEL": "deepseek-v4-flash",
                # Pin the interpreter so commit_scan.py (needs PyYAML) runs
                # even where the system `python3` lacks it.
                "PRAXIS_PYTHON": sys.executable,
            }
        )
        result = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env)
        return result.returncode
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.skipif(not _attribution_available(), reason="no harness session log (attribution unverifiable)")
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
