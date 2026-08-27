"""Test the three-system physical and runtime boundary contract."""

import json
import re
from pathlib import Path

import yaml

from scripts.py.check_system_boundaries import _manifest_path_dependencies, check_system_boundaries


def test_system_boundaries_are_clean() -> None:
    """Keep the manifest and runtime dependency graph within the declared boundary."""
    assert check_system_boundaries() == []


def test_legacy_runtime_roots_are_absent() -> None:
    """Prevent accidental reintroduction of the pre-layout roots."""
    root = Path(__file__).resolve().parents[2]
    for legacy in ("src", "crates", "packages"):
        assert not (root / legacy).exists(), f"legacy runtime root reintroduced: {legacy}"


def test_system_artifact_names_are_language_specific() -> None:
    """Keep formal Rust/TypeScript artifacts distinct from the Python prototype."""
    manifest = (Path(__file__).resolve().parents[2] / "systems" / "system-boundaries.yaml").read_text(encoding="utf-8")
    assert "praxis-python-reference-runtime" in manifest
    assert "praxis-rust-kernel-engine" in manifest
    assert "@praxis/typescript-shell-engine" in manifest


def test_build_environment_is_declared_as_the_observer_perimeter() -> None:
    """Keep build tooling outside runtime artifacts while allowing cross-system tests."""
    manifest = (Path(__file__).resolve().parents[2] / "systems" / "system-boundaries.yaml").read_text(encoding="utf-8")
    assert "id: praxis-build-environment" in manifest
    assert "role: observer-and-driver" in manifest


def test_system_directories_use_explicit_kebab_case_identities() -> None:
    """Keep runtime directory names distinct and machine-readable."""
    root = Path(__file__).resolve().parents[2]
    manifest = yaml.safe_load((root / "systems" / "system-boundaries.yaml").read_text(encoding="utf-8"))
    systems = manifest["systems"]
    assert {entry["id"] for entry in systems} == {
        "python-reference-runtime",
        "rust-kernel-engine",
        "typescript-shell-engine",
    }
    for entry in systems:
        relative = Path(entry["path"])
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", relative.name)
        assert relative.name == entry["id"]
        system_root = root / relative
        assert system_root.is_dir()
        assert not system_root.is_symlink()


def test_declared_source_roots_stay_inside_their_system() -> None:
    """Prevent a source-root declaration from escaping its runtime boundary."""
    root = Path(__file__).resolve().parents[2]
    manifest = yaml.safe_load((root / "systems" / "system-boundaries.yaml").read_text(encoding="utf-8"))
    for entry in manifest["systems"]:
        system_root = (root / entry["path"]).resolve()
        for source_root in entry["source_roots"]:
            source_path = (root / source_root).resolve()
            assert source_path == system_root or system_root in source_path.parents


def test_typescript_local_package_specs_are_resolved(tmp_path: Path) -> None:
    """Catch file/link dependency strings that bypass keyed manifest checks."""
    package = tmp_path / "package.json"
    package.write_text(
        json.dumps(
            {
                "dependencies": {"sibling": "file:../sibling-system"},
                "devDependencies": {"linked": "link:../linked-system"},
            }
        ),
        encoding="utf-8",
    )
    dependencies = _manifest_path_dependencies(package, "typescript")
    assert (package.parent / "../sibling-system").resolve() in dependencies
    assert (package.parent / "../linked-system").resolve() in dependencies
