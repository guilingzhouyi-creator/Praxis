"""Verify the bounded Rust test-domain runner stays aligned with Cargo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "py" / "run_rust_test_domains.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the domain runner through the active Python environment."""
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_runner_lists_all_declared_domains_and_targets() -> None:
    """Keep the bounded runner coupled to explicit Cargo targets."""
    result = _run("--list")

    assert result.returncode == 0, result.stderr
    assert "assembly: 7 target(s)" in result.stdout
    assert "network: 6 target(s)" in result.stdout
    assert "terminal: 5 target(s)" in result.stdout
    assert "  - process_table_group_runtime" in result.stdout


def test_runner_dry_run_keeps_selected_targets_as_independent_commands() -> None:
    """Ensure a selected domain never collapses into one monolithic test run."""
    result = _run("--domain", "network", "--jobs", "2", "--dry-run")

    assert result.returncode == 0, result.stderr
    commands = [line for line in result.stdout.splitlines() if line.startswith("cargo test ")]
    assert len(commands) == 6
    assert all("--manifest-path" in command and "--test" in command for command in commands)
    targets = [command.rsplit("--test", 1)[-1].strip() for command in commands]
    assert targets == ["bus", "health", "network", "notify", "notify_vectors", "peer_vectors"]
