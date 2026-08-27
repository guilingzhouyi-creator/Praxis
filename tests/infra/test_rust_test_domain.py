"""Enforce the isolated, explicitly registered Rust integration-test domain."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUST_CRATE = ROOT / "systems" / "rust-kernel-engine" / "l1-kernel-rs"
RUST_SRC = RUST_CRATE / "src"
RUST_TESTS = RUST_CRATE / "tests"
RUST_MANIFEST = RUST_TESTS.parent / "Cargo.toml"
TEST_DOMAINS = {
    "assembly",
    "core",
    "network",
    "policy",
    "process",
    "protocol",
    "registry",
    "runtime",
    "session",
    "storage",
    "terminal",
}


def test_rust_kernel_tests_live_outside_implementation_modules() -> None:
    """Keep Rust tests in integration targets so public boundaries stay real."""
    assert RUST_TESTS.is_dir(), "Rust kernel must provide a dedicated tests directory"
    root_files = sorted(RUST_TESTS.glob("*.rs"))
    assert not root_files, "Rust kernel tests must be grouped under tests/<domain>/"

    domain_dirs = {path.name for path in RUST_TESTS.iterdir() if path.is_dir()}
    assert domain_dirs == TEST_DOMAINS, (
        "Rust test domains must match the declared architecture: "
        f"expected {sorted(TEST_DOMAINS)}, found {sorted(domain_dirs)}"
    )

    nested_tests = sorted(path for path in RUST_TESTS.rglob("*.rs") if path.parent != RUST_TESTS)
    assert nested_tests, "Rust kernel test domain must contain integration targets"

    manifest = tomllib.loads(RUST_MANIFEST.read_text(encoding="utf-8"))
    assert manifest.get("package", {}).get("autotests") is False, (
        "Cargo implicit test discovery must stay disabled; register every target explicitly"
    )
    targets = manifest.get("test", [])
    assert isinstance(targets, list), "Cargo manifest must use explicit [[test]] targets"

    registered_paths: list[Path] = []
    registered_names: list[str] = []
    for target in targets:
        name = target.get("name")
        path_value = target.get("path")
        assert isinstance(name, str) and isinstance(path_value, str), (
            "Every Rust integration target needs string name and path"
        )
        path = RUST_MANIFEST.parent / path_value
        assert path.is_file(), f"Cargo test target points to a missing file: {path_value}"
        relative = path.relative_to(RUST_TESTS)
        assert len(relative.parts) == 2, f"Rust test target must live directly under tests/<domain>/: {path_value}"
        assert relative.parts[0] in TEST_DOMAINS, f"Unknown Rust test domain: {relative.parts[0]}"
        # Source leaves use an explicit `kernel_test_` namespace when they
        # would collide with Python reference modules. Cargo target names are
        # kept stable so existing `cargo test --test <name>` commands remain
        # valid across the file-layout cleanup.
        source_stem = path.stem
        allowed_names = {source_stem}
        if source_stem.startswith("kernel_test_"):
            allowed_names.add(source_stem.removeprefix("kernel_test_"))
        assert name in allowed_names, (
            f"Cargo target name must match its normalized source identity: {name!r} vs {path_value}"
        )
        registered_paths.append(path)
        registered_names.append(name)

    assert len(registered_names) == len(set(registered_names)), "Rust test target names must be unique"
    assert set(registered_paths) == set(nested_tests), (
        "Every Rust test file must be explicitly registered once in Cargo.toml"
    )

    forbidden = ("#[cfg(test)]", "#[test]", "#[bench]", "mod tests {")
    violations: list[str] = []
    for source in sorted(RUST_SRC.rglob("*.rs")):
        text = source.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                violations.append(f"{source.relative_to(ROOT)} contains {marker}")

    assert not violations, "Rust implementation modules must not embed tests:\n" + "\n".join(violations)
