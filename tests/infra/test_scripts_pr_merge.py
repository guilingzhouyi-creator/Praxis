"""Tests for scripts/sh/verify-pr-merge.sh — the pre-merge PR gate.

Drives the bash verifier against scratch git repos that sign commits with a
real ephemeral GPG key (generated per test into a temp GNUPGHOME), asserting
exit codes: unsigned commits fail (1), CJK / non-conventional subjects fail
(2), merge conflicts fail (4), and a fully signed conventional branch passes
(0). Tests skip cleanly when gpg is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "sh" / "verify-pr-merge.sh"
HUNK_AUDIT = ROOT / "scripts" / "py" / "audit_merge_hunks.py"

requires_gpg = pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg is not installed")


class ScratchRepo:
    """Temp git repo with an ephemeral GPG key for signed commits."""

    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path / "repo"
        self.dir.mkdir()
        self.gnupg = tmp_path / "gnupg"
        self.gnupg.mkdir(mode=0o700)
        self.env = {**os.environ, "GNUPGHOME": str(self.gnupg)}
        subprocess.run(
            [
                "gpg",
                "--batch",
                "--passphrase",
                "",
                "--quick-generate-key",
                "Praxis Test <t@test.local>",
                "default",
                "default",
                "never",
            ],
            check=True,
            capture_output=True,
            env=self.env,
        )
        listing = subprocess.run(
            ["gpg", "--list-secret-keys", "--keyid-format=long"],
            check=True,
            capture_output=True,
            text=True,
            env=self.env,
        ).stdout
        # Parse the key id from the `sec` line (stdout may start with a
        # keyring path line, so never split the whole listing).
        self.key_id = ""
        for line in listing.splitlines():
            if line.startswith("sec"):
                self.key_id = line.split()[1].split("/")[1]
                break
        assert self.key_id, f"no secret key found in: {listing!r}"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.dir)], check=True)
        # Neutralize any global hooksPath so temp-repo commits stay hermetic.
        (tmp_path / "no-hooks").mkdir()
        for key, value in (
            ("user.email", "t@test.local"),
            ("user.name", "Praxis Test"),
            ("user.signingkey", self.key_id),
            ("commit.gpgsign", "true"),
            ("core.hooksPath", str(tmp_path / "no-hooks")),
        ):
            subprocess.run(["git", "config", key, value], check=True, cwd=self.dir)
        (self.dir / "scripts" / "py").mkdir(parents=True)
        shutil.copy2(HUNK_AUDIT, self.dir / "scripts" / "py" / "audit_merge_hunks.py")
        self.commit("feat(core): base", {"f.txt": "hi"}, signed=True)

    def commit(self, subject: str, files: dict[str, str], signed: bool = True) -> None:
        for name, content in files.items():
            (self.dir / name).write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], check=True, cwd=self.dir, env=self.env)
        cmd = ["git"]
        if not signed:
            cmd += ["-c", "commit.gpgsign=false"]
        cmd += ["commit", "-q", "-m", subject]
        if signed:
            cmd += ["-S"]
        subprocess.run(cmd, check=True, cwd=self.dir, env=self.env)

    def branch(self, name: str) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", name],
            check=True,
            cwd=self.dir,
            env=self.env,
        )

    def verify(self, branch: str = "") -> subprocess.CompletedProcess:
        cmd = ["bash", str(SCRIPT)]
        if branch:
            cmd.append(branch)
        return subprocess.run(cmd, cwd=self.dir, capture_output=True, text=True, env=self.env)


def test_not_in_repo_usage_error(tmp_path):
    result = subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 3


def test_unknown_branch_usage_error(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo_dir)], check=True)
    result = subprocess.run(
        ["bash", str(SCRIPT), "no-such-branch"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 3


@requires_gpg
def test_unsigned_pr_rejected(tmp_path):
    repo = ScratchRepo(tmp_path)
    repo.branch("feature/unsigned")
    repo.commit("feat(x): unsigned work", {"g.txt": "1"}, signed=False)
    result = repo.verify("feature/unsigned")
    assert result.returncode == 1
    assert "UNSIGNED" in result.stderr


@requires_gpg
def test_cjk_subject_rejected(tmp_path):
    repo = ScratchRepo(tmp_path)
    repo.branch("feature/cjk")
    repo.commit("feat: 中文摘要", {"g.txt": "1"}, signed=True)
    result = repo.verify("feature/cjk")
    assert result.returncode == 2
    assert "CJK subject" in result.stderr


@requires_gpg
def test_non_conventional_subject_rejected(tmp_path):
    repo = ScratchRepo(tmp_path)
    repo.branch("feature/plain")
    repo.commit("Update readme", {"g.txt": "1"}, signed=True)
    result = repo.verify("feature/plain")
    assert result.returncode == 2
    assert "non-conventional" in result.stderr


@requires_gpg
def test_clean_signed_pr_passes(tmp_path):
    repo = ScratchRepo(tmp_path)
    repo.branch("feature/good")
    repo.commit("feat(core): add widget", {"g.txt": "1"})
    repo.commit("fix(core): wire widget", {"h.txt": "2"})
    result = repo.verify("feature/good")
    assert result.returncode == 0
    assert "safe to merge" in result.stdout


@requires_gpg
def test_no_incoming_commits_passes(tmp_path):
    repo = ScratchRepo(tmp_path)
    repo.branch("feature/empty")
    result = repo.verify("feature/empty")
    assert result.returncode == 0
    assert "no incoming commits" in result.stdout


@requires_gpg
def test_merge_conflict_detected(tmp_path):
    repo = ScratchRepo(tmp_path)
    repo.branch("feature/conflict")
    repo.commit("feat(a): edit shared", {"f.txt": "branch"})
    subprocess.run(
        ["git", "checkout", "-q", "main"],
        check=True,
        cwd=repo.dir,
        env=repo.env,
    )
    repo.commit("feat(b): edit shared too", {"f.txt": "main"})
    result = repo.verify("feature/conflict")
    assert result.returncode == 4
    assert "conflict" in result.stderr.lower()
