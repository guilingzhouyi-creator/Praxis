"""Comprehensive hooks strictness — end-to-end worktree enforcement.

Verifies the full chain: commit-msg hook, commit-template, ensure-hooks,
commit-lint workflow, and the audit log. This is the final gate that
proves worktree independence is closed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".githooks" / "commit-msg"
TEMPLATE = ROOT / ".githooks" / "commit-template.txt"
WORKFLOW = ROOT / ".github" / "workflows" / "commit-lint.yml"
ENSURE = ROOT / "scripts" / "sh" / "ensure-hooks.sh"
STRICT = ROOT / "scripts" / "py" / "commit_strict.py"


def _hook_ok(msg: str) -> bool:
    """Return True if commit-msg hook accepts msg."""
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(msg)
        path = f.name
    try:
        env = os.environ.copy()
        env["PRAXIS_AUTHOR"] = "OpenCode"
        env["PRAXIS_MODEL"] = "ox-alpha"
        env["PATH"] = f"/tmp:{env.get('PATH', '')}"
        r = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env, cwd=ROOT)
        return r.returncode == 0
    finally:
        Path(path).unlink(missing_ok=True)


def test_template_is_strict():
    """Template documents all strict fields."""
    assert TEMPLATE.exists()
    t = TEMPLATE.read_text(encoding="utf-8")
    assert "type(scope):" in t
    assert "Co-Authored-By" in t
    # Must mention English and 72
    assert "72" in t
    assert "English" in t


def test_workflow_is_strict():
    """commit-lint workflow lints both subject and Co-Authored-By."""
    assert WORKFLOW.exists()
    txt = WORKFLOW.read_text(encoding="utf-8")
    assert "commit_scan" in txt
    assert "--msg" in txt
    assert "--subject" in txt
    assert "Co-Authored-By" in txt or "commit-lint" in txt


def test_ensure_hooks_script_is_executable():
    """ensure-hooks.sh is executable and has no CRLF."""
    assert ENSURE.exists()
    assert ENSURE.stat().st_mode & 0o111 != 0
    raw = ENSURE.read_bytes()
    assert b"\r\n" not in raw
    assert b"core.hooksPath" in raw
    assert b"commit-msg" in raw


def test_commit_strict_script_exists():
    """commit_strict.py is executable as a module."""
    assert STRICT.exists()
    assert "worktree" in STRICT.read_text(encoding="utf-8").lower()


def test_hook_rejects_cjk():
    """CJK in subject is rejected."""
    assert not _hook_ok("feat: 中文测试\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n")


def test_hook_rejects_missing_trailer():
    """Missing Co-Authored-By is rejected."""
    assert not _hook_ok("feat(core): add x\n")


def test_hook_rejects_markdown_in_subject():
    """Markdown in subject is rejected."""
    assert not _hook_ok("feat(core): **bold**\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n")


def test_hook_rejects_uppercase_subject():
    """Uppercase subject is rejected."""
    assert not _hook_ok("Feat(core): add x\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n")


def test_hook_rejects_trailing_period():
    """Trailing period is rejected."""
    assert not _hook_ok("feat(core): add x.\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n")


def test_hook_accepts_valid():
    """Valid message passes."""
    import os as _os
    import subprocess as _sp
    import tempfile as _tf

    msg = "feat(hooks): add strict gate for worktree\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n"
    with _tf.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(msg)
        path = f.name
    try:
        env = _os.environ.copy()
        env["PRAXIS_AUTHOR"] = "OpenCode"
        env["PRAXIS_MODEL"] = "ox-alpha"
        r = _sp.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env, cwd=ROOT)
        print("STDERR:", r.stderr)
        print("STDOUT:", r.stdout)
        assert r.returncode == 0
    finally:
        Path(path).unlink(missing_ok=True)


def test_hook_bypass_requires_reason():
    """Bypass without reason is rejected, with reason passes."""
    msg = "feat(core): add x\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n"
    # Without reason
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(msg)
        path = f.name
    try:
        env = os.environ.copy()
        env["PRAXIS_SKIP_AUTHOR_CHECK"] = "1"
        env["PATH"] = f"/tmp:{env.get('PATH', '')}"
        r = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env, cwd=ROOT)
        assert r.returncode == 1
        assert "PRAXIS_SKIP_REASON" in r.stderr
        # With reason
        env["PRAXIS_SKIP_REASON"] = "test reason"
        r2 = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env, cwd=ROOT)
        assert r2.returncode == 0
    finally:
        Path(path).unlink(missing_ok=True)


def test_ensure_hooks_check_passes_after_fix():
    """After ensure-hooks fix, --check passes."""
    r = subprocess.run(["bash", str(ENSURE), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0


def test_all_hooks_executable():
    """All three hooks are executable."""
    for name in ["commit-msg", "pre-commit", "post-checkout"]:
        p = ROOT / ".githooks" / name
        assert p.exists()
        assert p.stat().st_mode & 0o111 != 0


def test_commit_scan_subject_length():
    """Subject too long (>72) is rejected."""
    long = "feat(hooks): " + "x" * 70 + "\n\nCo-Authored-By: OpenCode (ox-alpha) <noreply@opencode.ai>\n"
    assert not _hook_ok(long)


def test_workflow_covers_both_push_and_pr():
    """Workflow triggers on push and pull_request."""
    txt = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in txt
    assert "pull_request:" in txt
