"""Tests for .githooks/commit-msg — the commit governance gate.

Drives the Node.js validation script with synthetic commit messages and
asserts its exit code, so the rules (English, Co-Authored-By,
Conventional-Commits type, Merge exemption) are machine-verified rather than
trusted by convention. The Node.js script replaces the previous Python3-based
commit_scan.py + detect_agent.py, removing the Python3 runtime dependency.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".githooks" / "commit-msg"

COAUTH = "Co-Authored-By: AtomCode (deepseek-v4-flash) <noreply@atomgit.com>"


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
                # Pin the Node.js interpreter so the hook finds it reliably.
                "PRAXIS_NODE": "/home/guiling/.nvm/versions/node/v24.19.0/bin/node",
            }
        )
        result = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env)
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


# ── must_include gate (commit-time type-to-file matching) ────────────────


def _stage_tmp(rel_path: str) -> str:
    """Stage a temporary NEW file (a real staged diff) and return its path.

    `git add` of an already-tracked unchanged file produces no staged diff,
    so the gate's `git diff --cached` would be empty; a fresh file is the
    only way to exercise the type-to-file matching in a test.
    """
    import pathlib
    import subprocess as _sp

    p = pathlib.Path(rel_path)
    p.write_text("# temporary gate-scan fixture\n")
    _sp.run(["git", "add", str(p)], cwd=ROOT, check=True)
    return str(p)


def _unstage_tmp(rel_path: str) -> None:
    import pathlib
    import subprocess as _sp

    _sp.run(["git", "rm", "--cached", "-q", rel_path], cwd=ROOT, check=True)
    pathlib.Path(rel_path).unlink(missing_ok=True)


def test_perf_type_with_only_tests_files_rejected():
    # perf must touch src/crates/packages — a tests/-only change is now
    # blocked at commit time (mirrors commit_scan.py, previously push-time).
    p = _stage_tmp("tests/infra/_tmp_gate_scan.py")
    try:
        assert run_hook(f"perf(tests): parameterize gate scan\n\n{COAUTH}\n") == 1
    finally:
        _unstage_tmp(p)


def test_perf_type_with_src_file_passes():
    # A src/ temp file satisfies perf's must_include (src/crates/packages).
    p = _stage_tmp("src/l2/_tmp_gate_scan.py")
    try:
        assert run_hook(f"perf(l2): optimize dispatch\n\n{COAUTH}\n") == 0
    finally:
        _unstage_tmp(p)
