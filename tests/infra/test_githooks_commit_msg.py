"""Tests for .githooks/commit-msg — the commit governance gate.

Drives the bash hook with synthetic commit messages and asserts its exit code,
so the rules (English, Co-Authored-By, Conventional-Commits type, Merge
exemption) are machine-verified rather than trusted by convention.
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
        env.update({"PRAXIS_AUTHOR": "AtomCode", "PRAXIS_MODEL": "deepseek-v4-flash"})
        result = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env)
        return result.returncode
    finally:
        Path(path).unlink(missing_ok=True)


def test_valid_conventional_passes():
    # A real feat commit stages source files — model that so the type-to-
    # content gate sees a qualifying path instead of judging an empty index.
    p = _stage_tmp_probe("systems/python-reference-runtime/_tmp_valid_probe.py")
    try:
        assert run_hook(f"feat(core): add token ring revocation\n\n{COAUTH}\n") == 0
    finally:
        _unstage_tmp_probe(p)


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


def test_git_generated_merge_single_line_still_exempt():
    # A pure git-generated merge (single line, no custom body) is NOT a
    # hand-authored message — even a long branch name stays exempt.
    long_subject = "Merge branch 'feature/" + "a" * 80 + "'\n"
    assert run_hook(long_subject) == 0


def test_custom_merge_subject_over_72_rejected():
    # A hand-authored merge message (custom body present) must respect the
    # 72-char subject contract; a long subject is now rejected.
    long_subject = "Merge branch 'feature/" + "b" * 80 + "'\n\n"
    assert run_hook(long_subject + "Hand-written merge body.\n") == 1


def test_custom_merge_subject_within_72_passes():
    # A custom merge body with a short subject still passes the hook.
    assert run_hook("Merge branch 'feature/x'\n\nHand-written merge body.\n") == 0


# ── shared-file handoff gate (strict — register or reject) ───────────────


def _stage_tmp_probe(rel_path: str) -> str:
    """Stage a temporary NEW file (a real staged diff) and return its path."""
    import pathlib
    import subprocess as _sp

    p = pathlib.Path(rel_path)
    p.write_text("# temporary gate-scan probe\n")
    _sp.run(["git", "add", str(p)], cwd=ROOT, check=True)
    return str(p)


def _unstage_tmp_probe(rel_path: str) -> None:
    import pathlib
    import subprocess as _sp

    _sp.run(["git", "rm", "--cached", "-q", rel_path], cwd=ROOT, check=True)
    pathlib.Path(rel_path).unlink(missing_ok=True)


def _stage_existing(rel_path: str) -> None:
    import subprocess as _sp

    _sp.run(["git", "add", rel_path], cwd=ROOT, check=True)


def _unstage_existing(rel_path: str) -> None:
    import subprocess as _sp

    _sp.run(["git", "restore", "--staged", rel_path], cwd=ROOT, check=True)


def test_shared_file_change_without_registration_rejected():
    # scripts/sh is a shared dir — touching it without an ALIGNMENT.md
    # registration in the same commit is rejected (strict handoff gate).
    p = _stage_tmp_probe("scripts/sh/_tmp_probe.sh")
    try:
        assert (
            run_hook(f"fix(scripts): probe the shared file handoff gate\n\n## What\n- **probe**\n- x\n\n{COAUTH}\n")
            == 1
        )
    finally:
        _unstage_tmp_probe(p)


def test_shared_file_change_with_registration_passes():
    import pathlib

    p = _stage_tmp_probe("scripts/sh/_tmp_probe.sh")
    align = pathlib.Path("docs/agent-handoff/ALIGNMENT.md")
    original = align.read_text(encoding="utf-8")
    # Stage a REAL ALIGNMENT.md diff so the strict gate sees the registration
    # (git add of an unchanged file produces no staged diff).
    align.write_text(original + "| 2026-08-22 | test | test | staged registration | tmp |\n", encoding="utf-8")
    _stage_existing("docs/agent-handoff/ALIGNMENT.md")
    try:
        assert (
            run_hook(f"fix(scripts): probe the shared file handoff gate\n\n## What\n- **probe**\n- x\n\n{COAUTH}\n")
            == 0
        )
    finally:
        align.write_text(original, encoding="utf-8")
        _unstage_existing("docs/agent-handoff/ALIGNMENT.md")
        _unstage_tmp_probe(p)


# ── must_include gate (type-to-file matching — restored regression) ──────


def test_must_include_rejects_feat_without_source_files():
    # feat/fix/refactor must touch systems/python-reference-runtime/, systems/rust-kernel-engine/, systems/typescript-shell-engine/, scripts/, .githooks/, or config/
    # — a staged tests/ file alone does not qualify (validate-commit must_include).
    p = _stage_tmp_probe("tests/_tmp_must_include.py")
    try:
        assert run_hook(f"feat(core): probe the must include gate\n\n## What\n- **probe**\n- x\n\n{COAUTH}\n") == 1
    finally:
        _unstage_tmp_probe(p)


def test_must_include_passes_for_matching_type():
    # test type requires tests/ files — a staged tests/ file qualifies.
    p = _stage_tmp_probe("tests/_tmp_must_include.py")
    try:
        assert run_hook(f"test(core): probe the must include gate\n\n## What\n- **probe**\n- x\n\n{COAUTH}\n") == 0
    finally:
        _unstage_tmp_probe(p)
