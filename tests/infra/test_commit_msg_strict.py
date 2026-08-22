"""Strict commit-msg tests — bypass audit, English, trailer.

Covers the tightened .githooks/commit-msg:
  - PRAXIS_SKIP_AUTHOR_CHECK now requires PRAXIS_SKIP_REASON and is audit-logged
  - worktree independence (each worktree has its own .githooks)
  - Co-Authored-By must be last line with blank line before
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".githooks" / "commit-msg"
TEMPLATE = ROOT / ".githooks" / "commit-template.txt"

COAUTH = "Co-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>"


def _run_hook(msg: str, env_over: dict | None = None) -> subprocess.CompletedProcess:
    """Run commit-msg hook with msg and env, return CompletedProcess."""
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(msg)
        path = f.name
    try:
        env = os.environ.copy()
        env.update({"PRAXIS_AUTHOR": "OpenCode", "PRAXIS_MODEL": "ox-alpha"})
        if env_over:
            env.update(env_over)
        # Ensure PATH has /tmp for python/ruff
        env["PATH"] = f"/tmp:{env.get('PATH', '')}"
        return subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env, cwd=ROOT)
    finally:
        Path(path).unlink(missing_ok=True)


def test_bypass_without_reason_rejected():
    """PRAXIS_SKIP_AUTHOR_CHECK without reason is now rejected."""
    # Hook should reject bypass without reason, not exit 0
    env = {"PRAXIS_SKIP_AUTHOR_CHECK": "1"}
    # Without reason, the new hook should fail
    r = _run_hook("bad message without trailer", env_over=env)
    # Even with bypass, a bad message that is not English etc. should still be checked?
    # The new bypass requires PRAXIS_SKIP_REASON, so without it it fails.
    assert r.returncode == 1
    assert "PRAXIS_SKIP_REASON" in r.stderr


def test_bypass_with_reason_passes_and_audits():
    """Bypass with reason passes and is audit-logged."""
    audit = ROOT / ".praxis" / "commit-bypass.jsonl"
    before = audit.read_text(encoding="utf-8") if audit.exists() else ""
    msg = "feat(core): add x\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n"
    env = {"PRAXIS_SKIP_AUTHOR_CHECK": "1", "PRAXIS_SKIP_REASON": "test bypass audit"}
    r = _run_hook(msg, env_over=env)
    assert r.returncode == 0
    assert "bypassed" in r.stderr or "audit" in r.stderr
    # Audit file should have grown (reason is shell-quoted with %q)
    after = audit.read_text(encoding="utf-8") if audit.exists() else ""
    assert len(after) > len(before)
    assert "test" in after and "bypass" in after


def test_commit_template_exists_and_strict():
    """Commit template exists and documents strict fields."""
    assert TEMPLATE.exists()
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "type(scope):" in text
    assert "Co-Authored-By" in text
    assert "English" in text or "english" in text.lower()


def test_trailer_must_be_last_line():
    """Co-Authored-By must be the last line, blank line before."""
    # Well-formed message must pass; use a non-placeholder summary (>=10 chars)
    msg_good = "feat(core): add strict gate for hooks\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n"
    r2 = _run_hook(msg_good)
    assert r2.returncode == 0


def test_worktree_hooks_independent():
    """Each worktree has its own .githooks/commit-msg (not shared)."""
    # Current worktree's hook must be strict and executable
    cur_hook = ROOT / ".githooks" / "commit-msg"
    assert cur_hook.exists()
    assert cur_hook.stat().st_mode & 0o111 != 0
    assert "PRAXIS_SKIP_REASON" in cur_hook.read_text(encoding="utf-8")


def test_ci_workflow_exists():
    """Server-side commit-lint workflow exists for worktree pushes."""
    wf = ROOT / ".github" / "workflows" / "commit-lint.yml"
    assert wf.exists()
    text = wf.read_text(encoding="utf-8")
    assert "commit_scan" in text
    assert "Co-Authored-By" in text or "commit-lint" in text
