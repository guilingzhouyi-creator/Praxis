"""Regression tests for scripts/sh/handoff-rotate.sh — handoff-area rotation.

Uses HANDOFF_DIR to point the script at a temp directory so the real
docs/agent-handoff area is never touched by tests.
"""

from __future__ import annotations

import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "sh" / "handoff-rotate.sh"


def _run(hd: pathlib.Path, log_max: int = 30, keep: int = 30) -> subprocess.CompletedProcess[str]:
    env = {"HANDOFF_DIR": str(hd), "HANDOFF_LOG_MAX": str(log_max), "HANDOFF_KEEP": str(keep)}
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _make_align(hd: pathlib.Path, n: int) -> None:
    rows = "\n".join(f"| 2026-08-{i:02d} | file-{i} | agent | change | status |" for i in range(1, n + 1))
    (hd / "ALIGNMENT.md").write_text(
        "# Alignment State — live\n\n## Shared-file change log\n\n"
        "| Date | File | Agent | Change | Status |\n|---|---|---|---|---|\n" + rows + "\n\n## Clobber warnings\n",
        encoding="utf-8",
    )


def test_rotation_archives_old_entries(tmp_path):
    hd = tmp_path / "handoff"
    hd.mkdir()
    _make_align(hd, 5)  # 5 entries > LOG_MAX=2 -> rotate, keep newest 1
    r = _run(hd, log_max=2, keep=1)
    assert r.returncode == 0
    align = (hd / "ALIGNMENT.md").read_text(encoding="utf-8")
    assert "| 2026-08-01 |" not in align  # oldest rotated out
    assert "| 2026-08-05 |" in align  # newest kept
    archive = list((hd / "archive").glob("ALIGNMENT-*.md"))
    assert archive  # archive file created
    assert "| 2026-08-01 |" in archive[0].read_text(encoding="utf-8")


def test_within_threshold_no_change(tmp_path):
    hd = tmp_path / "handoff"
    hd.mkdir()
    _make_align(hd, 2)  # 2 <= LOG_MAX=5 -> no rotation
    r = _run(hd, log_max=5)
    assert r.returncode == 0
    assert "within thresholds" in r.stdout
    assert not list((hd / "archive").glob("*"))  # dir may exist, no archived files
