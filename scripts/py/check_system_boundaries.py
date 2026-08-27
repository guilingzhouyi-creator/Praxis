"""Validate the physical and runtime boundaries of Praxis systems.

The checker is intentionally small and dependency-aware: it validates the
machine-readable layout manifest, rejects legacy roots, verifies entrypoints,
and scans only runtime dependency declarations. Test files may use the
shared vectors and process-level probes; production source may not import a
different system's source tree.

    python scripts/py/check_system_boundaries.py
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "systems" / "system-boundaries.yaml"
EXPECTED_SYSTEM_IDS = {
    "python-reference-runtime",
    "rust-kernel-engine",
    "typescript-shell-engine",
}
EXPECTED_ARTIFACT_NAMES = {
    "praxis-python-reference-runtime",
    "praxis-rust-kernel-engine",
    "@praxis/typescript-shell-engine",
}

_RUST_DEPENDENCY_LINE = re.compile(
    r"^\s*(?:use|mod|extern\s+crate)\b|"
    r"\b(?:include_str|include_bytes)!\s*\(\s*[\"']|"
    r"^\s*#\s*\[\s*path\s*="
)
_TYPESCRIPT_DEPENDENCY_LINE = re.compile(
    r"^\s*(?:import|export)\b.*\bfrom\s*[\"']|"
    r"^\s*import\s*\(\s*[\"']|"
    r"\brequire\s*\(\s*[\"']"
)
_SYSTEM_DIRECTORY_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LANGUAGE_SUFFIXES = {
    "python": {".py"},
    "rust": {".rs"},
    "typescript": {".ts", ".tsx", ".mts", ".cts"},
}
_LOCAL_PACKAGE_SPEC_PREFIXES = ("file:", "link:")


def _load_manifest() -> dict[str, Any]:
    """Load and minimally validate the boundary manifest."""
    try:
        data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to read {MANIFEST}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("system boundary manifest must contain a mapping")
    return data


def _python_code_text(path: Path) -> str:
    """Return Python source with comments and docstrings removed."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return text

    lines = text.splitlines()
    blank_lines: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.lineno is not None
            and first.end_lineno is not None
        ):
            blank_lines.update(range(first.lineno, first.end_lineno + 1))

    result: list[str] = []
    for number, line in enumerate(lines, 1):
        if number in blank_lines or line.lstrip().startswith("#"):
            result.append("")
        else:
            result.append(line)
    return "\n".join(result)


def _dependency_text(path: Path, language: str) -> str:
    """Extract source lines that can establish a cross-system dependency."""
    if language == "python":
        return _python_code_text(path)

    pattern = _RUST_DEPENDENCY_LINE if language == "rust" else _TYPESCRIPT_DEPENDENCY_LINE
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if pattern.search(line))


def _forbidden_tokens(forbidden_paths: list[str]) -> set[str]:
    """Return path and directory tokens that identify a forbidden system."""
    tokens: set[str] = set()
    for forbidden_path in forbidden_paths:
        normalized = forbidden_path.rstrip("/\\")
        if normalized:
            tokens.add(normalized)
            tokens.add(Path(normalized).name)
    return tokens


def _is_within(path: Path, parent: Path) -> bool:
    """Return whether *path* resolves inside *parent*."""
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _relative_path(value: str) -> Path | None:
    """Return a safe repository-relative path, rejecting traversal and absolutes."""
    path = Path(value)
    if path == Path(".") or path.is_absolute() or ".." in path.parts:
        return None
    return path


def _source_files(root: Path, language: str) -> list[Path]:
    """List runtime source files for a declared language."""
    suffixes = _LANGUAGE_SUFFIXES.get(language, set())
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in suffixes and "__pycache__" not in path.parts
    )


def _iter_manifest_values(value: Any, keys: set[str]) -> list[str]:
    """Collect string values under mapping keys used for local path dependencies."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in keys and isinstance(child, str):
                found.append(child)
            found.extend(_iter_manifest_values(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_manifest_values(child, keys))
    return found


def _iter_local_package_specs(value: Any) -> list[str]:
    """Collect npm-style local package specs wherever they occur in JSON."""
    found: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            found.extend(_iter_local_package_specs(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_local_package_specs(child))
    elif isinstance(value, str) and value.startswith(_LOCAL_PACKAGE_SPEC_PREFIXES):
        found.append(value)
    return found


def _manifest_path_dependencies(manifest_file: Path, language: str) -> list[Path]:
    """Extract local dependency paths from a Rust or TypeScript manifest."""
    try:
        text = manifest_file.read_text(encoding="utf-8")
    except OSError:
        return []

    if language == "rust" and manifest_file.suffix == ".toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return []
        return [(manifest_file.parent / raw).resolve() for raw in _iter_manifest_values(data, {"path"})]

    if language == "typescript" and manifest_file.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        dependencies: list[Path] = []
        for raw in _iter_manifest_values(data, {"path"}):
            dependencies.append((manifest_file.parent / raw).resolve())
        for raw in _iter_local_package_specs(data):
            dependencies.append((manifest_file.parent / raw.split(":", 1)[1]).resolve())
        return dependencies

    return []


def _check_build_environment(manifest: dict[str, Any], violations: list[str]) -> None:
    """Ensure the build perimeter is present and explicitly non-runtime."""
    build_environment = manifest.get("build_environment")
    if not isinstance(build_environment, dict):
        violations.append("build_environment must be a mapping")
        return
    if build_environment.get("id") != "praxis-build-environment":
        violations.append("build_environment.id must be praxis-build-environment")
    if build_environment.get("role") != "observer-and-driver":
        violations.append("build_environment.role must be observer-and-driver")

    paths = build_environment.get("paths")
    if not isinstance(paths, list):
        violations.append("build_environment.paths must be a list")
    else:
        for relative_path in paths:
            if not isinstance(relative_path, str):
                violations.append("build_environment.paths entries must be strings")
                continue
            if not (ROOT / relative_path).exists():
                violations.append(f"build environment path is missing: {relative_path}")

    shared_inputs = build_environment.get("shared_test_inputs")
    if not isinstance(shared_inputs, list):
        violations.append("build_environment.shared_test_inputs must be a list")
    else:
        for relative_path in shared_inputs:
            if not isinstance(relative_path, str):
                violations.append("build_environment.shared_test_inputs entries must be strings")
                continue
            if not (ROOT / relative_path).exists():
                violations.append(f"shared test input path is missing: {relative_path}")


def check_system_boundaries() -> list[str]:
    """Return all boundary violations, or an empty list when valid."""
    try:
        manifest = _load_manifest()
    except ValueError as exc:
        return [str(exc)]

    violations: list[str] = []
    if manifest.get("schema_version") != 1:
        violations.append("systems/system-boundaries.yaml must use schema_version: 1")
    _check_build_environment(manifest, violations)

    for legacy in manifest.get("legacy_roots", []):
        if not isinstance(legacy, str):
            violations.append("legacy_roots entries must be strings")
            continue
        legacy_path = ROOT / legacy
        if os.path.lexists(legacy_path):
            violations.append(f"legacy root still exists: {legacy}")

    declared = manifest.get("systems")
    if not isinstance(declared, list):
        return violations + ["systems must be a list"]

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_artifacts: set[str] = set()
    declared_ids: set[str] = set()
    for item in declared:
        if not isinstance(item, dict):
            violations.append("each system entry must be a mapping")
            continue
        system_id = item.get("id")
        relative_path = item.get("path")
        artifact_name = item.get("artifact_name")
        language = item.get("language")
        if not all(isinstance(value, str) for value in (system_id, relative_path, artifact_name, language)):
            violations.append("each system needs string id, path, artifact_name, and language")
            continue
        if language not in _LANGUAGE_SUFFIXES:
            violations.append(f"{system_id}: unsupported language {language!r}")
        system_relative = _relative_path(relative_path)
        if system_relative is None:
            violations.append(f"{system_id}: path must be repository-relative without '..': {relative_path}")
            continue
        if not _SYSTEM_DIRECTORY_NAME.fullmatch(system_relative.name):
            violations.append(f"{system_id}: system directory must use lowercase kebab-case: {relative_path}")
        if system_relative.name != system_id:
            violations.append(f"{system_id}: path basename must match system id: {relative_path}")
        declared_ids.add(system_id)
        if system_id in seen_ids:
            violations.append(f"duplicate system id: {system_id}")
        seen_ids.add(system_id)
        if relative_path in seen_paths:
            violations.append(f"duplicate system path: {relative_path}")
        seen_paths.add(relative_path)
        if artifact_name in seen_artifacts:
            violations.append(f"duplicate artifact name: {artifact_name}")
        seen_artifacts.add(artifact_name)

        system_root = ROOT / system_relative
        if not system_root.is_dir():
            violations.append(f"{system_id}: missing system directory {relative_path}")
            continue
        if system_root.is_symlink():
            violations.append(f"{system_id}: system directory must not be a symlink: {relative_path}")

        forbidden = item.get("forbidden_runtime_paths", [])
        if not isinstance(forbidden, list):
            violations.append(f"{system_id}: forbidden_runtime_paths must be a list")
            forbidden = []
        for forbidden_path in forbidden:
            if not isinstance(forbidden_path, str):
                violations.append(f"{system_id}: forbidden path entries must be strings")
        forbidden_paths = [path for path in forbidden if isinstance(path, str)]

        entrypoints = item.get("entrypoints", [])
        if not isinstance(entrypoints, list):
            violations.append(f"{system_id}: entrypoints must be a list")
            entrypoints = []
        for entrypoint in entrypoints:
            if not isinstance(entrypoint, str):
                violations.append(f"{system_id}: entrypoints entries must be strings")
                continue
            entrypoint_path = ROOT / entrypoint
            if not entrypoint_path.is_file():
                violations.append(f"{system_id}: missing entrypoint {entrypoint}")
            elif not _is_within(entrypoint_path, system_root):
                violations.append(f"{system_id}: entrypoint outside system directory: {entrypoint}")

        source_roots = item.get("source_roots", [])
        if not isinstance(source_roots, list) or not source_roots:
            violations.append(f"{system_id}: source_roots must be a non-empty list")
            source_roots = []
        for source_root in source_roots:
            if not isinstance(source_root, str):
                violations.append(f"{system_id}: source_roots entries must be strings")
                continue
            source_relative = _relative_path(source_root)
            if source_relative is None:
                violations.append(f"{system_id}: source root must be repository-relative without '..': {source_root}")
                continue
            source_dir = ROOT / source_relative
            if not source_dir.is_dir():
                violations.append(f"{system_id}: missing source root {source_root}")
                continue
            if source_dir.is_symlink():
                violations.append(f"{system_id}: source root must not be a symlink: {source_root}")
            if not _is_within(source_dir, system_root):
                violations.append(f"{system_id}: source root outside system directory: {source_root}")
            forbidden_tokens = _forbidden_tokens(forbidden_paths)
            for source_file in _source_files(source_dir, language):
                if source_file.is_symlink():
                    violations.append(f"{source_file.relative_to(ROOT)} is a symlinked runtime source file")
                    continue
                dependency_text = _dependency_text(source_file, language)
                for token in forbidden_tokens:
                    if token in dependency_text:
                        violations.append(f"{source_file.relative_to(ROOT)} references forbidden runtime token {token}")

        build_manifests = item.get("build_manifests", [])
        if not isinstance(build_manifests, list):
            violations.append(f"{system_id}: build_manifests must be a list")
            continue
        for manifest_path in build_manifests:
            if not isinstance(manifest_path, str):
                violations.append(f"{system_id}: build_manifests entries must be strings")
                continue
            manifest_file = ROOT / manifest_path
            if not manifest_file.is_file():
                violations.append(f"{system_id}: missing build manifest {manifest_path}")
                continue
            try:
                manifest_text = manifest_file.read_text(encoding="utf-8")
            except OSError as exc:
                violations.append(f"{system_id}: unable to read build manifest {manifest_path}: {exc}")
                continue
            for forbidden_path in forbidden_paths:
                token = forbidden_path.rstrip("/\\")
                if token and token in manifest_text:
                    violations.append(f"{manifest_file.relative_to(ROOT)} references forbidden build path {token}")
            for dependency_path in _manifest_path_dependencies(manifest_file, language):
                for forbidden_path in forbidden_paths:
                    forbidden_root = (ROOT / forbidden_path).resolve()
                    if _is_within(dependency_path, forbidden_root):
                        violations.append(
                            f"{manifest_file.relative_to(ROOT)} resolves a forbidden build dependency "
                            f"into {forbidden_path}"
                        )

    if declared_ids != EXPECTED_SYSTEM_IDS:
        violations.append(
            "declared systems must be exactly "
            + ", ".join(sorted(EXPECTED_SYSTEM_IDS))
            + f"; found {', '.join(sorted(declared_ids)) or '<none>'}"
        )
    if seen_artifacts != EXPECTED_ARTIFACT_NAMES:
        violations.append(
            "declared artifact names must be exactly "
            + ", ".join(sorted(EXPECTED_ARTIFACT_NAMES))
            + f"; found {', '.join(sorted(seen_artifacts)) or '<none>'}"
        )
    if len(seen_paths) != len(declared_ids):
        violations.append("system directory names must be unique")
    return violations


def main() -> int:
    """Run the boundary check and print a concise machine-readable result."""
    violations = check_system_boundaries()
    if violations:
        print("SYSTEM_BOUNDARIES: FAIL")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("SYSTEM_BOUNDARIES: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
