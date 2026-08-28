"""Verify the bounded Rust test-domain runner stays aligned with Cargo."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "py" / "run_rust_test_domains.py"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the domain runner through the active Python environment."""
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=10,
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


def test_runner_rejects_non_positive_or_non_finite_timeout() -> None:
    """Require every target process to have a real execution bound."""
    for value in ("0", "-1", "nan", "inf"):
        result = _run("--timeout", value, "--dry-run")

        assert result.returncode == 2
        assert "--timeout must be a finite value greater than zero" in result.stderr


def test_runner_terminates_timed_out_cargo_process_groups(tmp_path: Path) -> None:
    """Turn a hung Cargo target into a bounded, reportable slice failure."""
    fake_cargo = tmp_path / "cargo"
    fake_cargo.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    fake_cargo.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    result = _run("--domain", "network", "--jobs", "1", "--timeout", "0.05", env=env)

    assert result.returncode == 1
    assert result.stdout.count("[TIMEOUT] network/") == 6
    assert "target timed out after 0.05s; process group terminated" in result.stdout
    assert "Rust test slices: 0 passed, 6 failed" in result.stdout


def test_runner_hides_passing_target_output_unless_verbose(tmp_path: Path) -> None:
    """Keep normal slice logs compact while retaining an explicit verbose mode."""
    fake_cargo = tmp_path / "cargo"
    fake_cargo.write_text("#!/bin/sh\necho passing-target-output\n", encoding="utf-8")
    fake_cargo.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"

    compact = _run("--domain", "network", "--jobs", "1", env=env)
    verbose = _run("--domain", "network", "--jobs", "1", "--verbose", env=env)

    assert compact.returncode == 0
    assert "passing-target-output" not in compact.stdout
    assert "[PASS] network/bus" in compact.stdout
    assert verbose.returncode == 0
    assert verbose.stdout.count("passing-target-output") == 6
