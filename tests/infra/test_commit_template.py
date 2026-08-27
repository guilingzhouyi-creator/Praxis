"""Tests for commit template — strict fields and config."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = ROOT / ".githooks" / "commit-template.txt"
SCRIPT = ROOT / "scripts" / "py" / "commit_gate.py"


def test_template_exists_and_strict():
    """Template exists and documents strict fields."""
    assert TEMPLATE.exists()
    txt = TEMPLATE.read_text(encoding="utf-8")
    assert "type(scope):" in txt
    assert "Co-Authored-By" in txt
    assert "72" in txt
    assert "English" in txt
    # blank line before the trailer example — raw or commented presentation
    assert "\n\nCo-Authored-By" in txt or "\n#\n# Co-Authored-By" in txt


def test_template_check_passes():
    """commit_gate.py template --check passes on strict repo."""
    r = subprocess.run(["python", str(SCRIPT), "template", "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_template_has_example():
    """Template contains an example commit."""
    txt = TEMPLATE.read_text(encoding="utf-8")
    assert "feat(" in txt or "fix(" in txt
    assert "Co-Authored-By:" in txt
