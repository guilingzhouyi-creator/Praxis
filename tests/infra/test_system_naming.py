"""Test the language-native leaf naming contract."""

from pathlib import Path

from scripts.py.check_system_naming import check_system_naming


def test_system_leaf_naming_is_clean() -> None:
    """Keep formal Rust and TypeScript leaves distinct from Python references."""
    assert check_system_naming() == []


def test_formal_leaf_names_use_explicit_domains() -> None:
    """Keep representative protocol and kernel leaves visibly language-specific."""
    root = Path(__file__).resolve().parents[2]
    assert (root / "systems/rust-kernel-engine/l1-kernel-rs/src/kernel_event.rs").is_file()
    assert (root / "systems/typescript-shell-engine/src/wire-envelope.ts").is_file()
    assert not (root / "systems/rust-kernel-engine/l1-kernel-rs/src/event.rs").exists()
    assert not (root / "systems/typescript-shell-engine/src/envelope.ts").exists()
