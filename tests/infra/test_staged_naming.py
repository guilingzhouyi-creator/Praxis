"""Test the commit-time staged naming gate (dir kebab + hierarchy/ownership)."""

from pathlib import Path

from scripts.py.check_system_naming import (
    _check_staged_dir_hierarchy,
    _load_rules,
)

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "config" / "discovery" / "naming-rules.yaml"


def _violations(paths: list[str]) -> list[str]:
    rules = _load_rules(RULES)
    return _check_staged_dir_hierarchy([Path(p) for p in paths], rules)


def test_rules_config_loads() -> None:
    """The naming-rules config is present and well-formed."""
    rules = _load_rules(RULES)
    assert rules["dir_segments"] == "kebab_case"
    assert set(rules["systems"]) == {"typescript-shell-engine", "rust-kernel-engine"}


def test_clean_staged_paths_pass() -> None:
    """Known-good formal leaves produce no violations."""
    good = [
        "systems/typescript-shell-engine/src/engine/parser.ts",
        "systems/typescript-shell-engine/src/engine/transports/line-transport.ts",
        "systems/typescript-shell-engine/src/protocol/wire-envelope.ts",
        "systems/typescript-shell-engine/src/i18n/locale-catalog.ts",
        "systems/typescript-shell-engine/src/telemetry/terminal-input-telemetry.ts",
        "systems/typescript-shell-engine/tests/shell-protocol.test.ts",
        "systems/rust-kernel-engine/l1-kernel-rs/src/kernel_event.rs",
        "systems/rust-kernel-engine/l1-kernel-rs/src/bin/rust-kernel-entry.rs",
    ]
    assert _violations(good) == []


def test_loose_src_root_file_rejected() -> None:
    """A file directly under src/ violates no_root_files."""
    v = _violations(["systems/typescript-shell-engine/src/loose.ts"])
    assert len(v) == 1
    assert "loose file" in v[0]


def test_undeclared_subdir_rejected() -> None:
    """A new top-level src subdir must be declared in the rules."""
    v = _violations(["systems/typescript-shell-engine/src/misc/x.ts"])
    assert len(v) == 1
    assert "undeclared subdirectory" in v[0]


def test_ownership_prefix_enforced() -> None:
    """protocol/ leaves must use the wire- prefix."""
    v = _violations(["systems/typescript-shell-engine/src/protocol/envelope.ts"])
    assert len(v) == 1
    assert "prefix 'wire-'" in v[0]


def test_ownership_exact_enforced() -> None:
    """i18n/ and telemetry/ leaves must match their exact stems."""
    v = _violations(["systems/typescript-shell-engine/src/i18n/strings.ts"])
    assert len(v) == 1
    assert "exactly 'locale-catalog'" in v[0]


def test_bench_in_src_rejected() -> None:
    """Benchmark sources must live under bench/, not src/."""
    v = _violations(["systems/typescript-shell-engine/src/engine/bench.ts"])
    assert len(v) == 1
    assert "benchmark source" in v[0]


def test_non_kebab_directory_rejected() -> None:
    """Directory segments must be lowercase kebab-case."""
    v = _violations(["systems/typescript-shell-engine/src/Engine/parser.ts"])
    assert any("not lowercase kebab-case" in item for item in v)
