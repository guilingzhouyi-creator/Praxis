"""Enforce the isolated integration-test domain for the Rust kernel."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUST_SRC = ROOT / "crates" / "l1-kernel-rs" / "src"
RUST_TESTS = ROOT / "crates" / "l1-kernel-rs" / "tests"


def test_rust_kernel_tests_live_outside_implementation_modules() -> None:
    """Keep Rust tests in integration targets so public boundaries stay real."""
    assert RUST_TESTS.is_dir(), "Rust kernel must provide a dedicated tests directory"
    assert any(RUST_TESTS.glob("*.rs")), "Rust kernel test domain must contain integration targets"

    forbidden = ("#[cfg(test)]", "#[test]", "#[bench]", "mod tests {")
    violations: list[str] = []
    for source in sorted(RUST_SRC.rglob("*.rs")):
        text = source.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                violations.append(f"{source.relative_to(ROOT)} contains {marker}")

    assert not violations, "Rust implementation modules must not embed tests:\n" + "\n".join(violations)
