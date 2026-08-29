"""Validate language-native leaf names across the three Praxis systems.

The Python tree is the semantic reference, so formal Rust and TypeScript
leaves must not reuse its normalized basename. This keeps source navigation,
tooling output, and future clean-break rewrites unambiguous without changing
the public Rust module API. Rust integration-test leaves are checked too:
collision-prone targets use the ``kernel_test_`` source prefix while Cargo
target names remain stable.

    python scripts/py/check_system_naming.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "systems" / "system-boundaries.yaml"

_STYLES = {
    "python": re.compile(r"^_*[a-z0-9]+(?:_[a-z0-9]+)*$"),
    "rust": re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$"),
    "typescript": re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
}
_SUFFIXES = {
    "python": {".py"},
    "rust": {".rs"},
    "typescript": {".ts", ".tsx", ".mts", ".cts"},
}
_EXPECTED_NAMING = {
    "python": ("snake_case", "reference-baseline"),
    "rust": ("snake_case", "distinct-from-python"),
    "typescript": ("kebab_case", "distinct-from-python"),
}
_IGNORED_PYTHON_STEMS = {"__init__", "__main__"}

# Commit-time naming rules (hierarchy/ownership) — single source of truth.
RULES_DEFAULT = ROOT / "config" / "discovery" / "naming-rules.yaml"
_DIR_STYLE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Stable system identities (project-structure.md "System names are explicit").
FORMAL_SYSTEM_DIRS = (
    Path("systems/typescript-shell-engine"),
    Path("systems/rust-kernel-engine"),
)


def _load_manifest(manifest_path: Path = MANIFEST) -> dict[str, Any]:
    """Load the system boundary manifest."""
    try:
        value = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to read {manifest_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("system boundary manifest must contain a mapping")
    return value


def _source_files(root: Path, language: str) -> list[Path]:
    """Return source files for one declared system language."""
    suffixes = _SUFFIXES[language]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in suffixes and "node_modules" not in path.parts
    )


def _leaf_stem(path: Path, language: str, *, test: bool = False) -> str | None:
    """Return the language-native logical stem for a source leaf."""
    stem = path.stem
    if language == "typescript" and test:
        if not stem.endswith(".test"):
            return None
        # Vitest keeps the `.test.ts` suffix; dots in the logical test name
        # are treated as domain separators before kebab-case validation.
        stem = stem[: -len(".test")].replace(".", "-")
    return stem


def _normalise_stem(path: Path, language: str, *, test: bool = False) -> str:
    """Normalize a source stem for cross-language collision checks."""
    stem = _leaf_stem(path, language, test=test) or path.stem
    return stem.replace("-", "_") if language == "typescript" else stem


def check_system_naming(
    root: Path = ROOT,
    manifest_path: Path = MANIFEST,
) -> list[str]:
    """Return naming violations, or an empty list when the layout is clean."""
    try:
        manifest = _load_manifest(manifest_path)
    except ValueError as exc:
        return [str(exc)]

    entries = manifest.get("systems")
    if not isinstance(entries, list):
        return ["systems must be a list"]

    by_language: dict[str, tuple[dict[str, Any], Path]] = {}
    violations: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            violations.append("each system entry must be a mapping")
            continue
        language = entry.get("language")
        relative = entry.get("path")
        naming = entry.get("naming")
        if not isinstance(language, str) or not isinstance(relative, str):
            violations.append("each system needs language and path for naming checks")
            continue
        if language not in _STYLES:
            violations.append(f"unsupported naming language: {language}")
            continue
        if not isinstance(naming, dict):
            violations.append(f"{language}: naming must be a mapping")
            continue
        expected_style, expected_role = _EXPECTED_NAMING[language]
        if naming.get("filename_style") != expected_style:
            violations.append(f"{language}: naming.filename_style must be {expected_style}")
        if naming.get("basename_role") != expected_role:
            violations.append(f"{language}: naming.basename_role must be {expected_role}")
        if language == "rust" and naming.get("collision_prefix") != "kernel_":
            violations.append("rust: naming.collision_prefix must be kernel_")
        system_root = root / relative
        if not system_root.is_dir():
            violations.append(f"{language}: missing system directory {relative}")
            continue
        by_language[language] = (entry, system_root)

    source_stems: dict[str, set[str]] = defaultdict(set)
    # Source and test leaves share a language namespace but may intentionally
    # mirror one another (for example, `engine.ts` and `engine.test.ts`).
    # Track duplicate leaves within each boundary kind while still checking
    # both kinds against the Python reference namespace below.
    formal_paths: dict[tuple[str, str], dict[str, Path]] = defaultdict(dict)
    for language, (entry, _system_root) in by_language.items():
        style = _STYLES[language]
        source_roots = entry.get("source_roots")
        if not isinstance(source_roots, list) or not source_roots:
            violations.append(f"{language}: naming source_roots must be a non-empty list")
            continue
        for raw_source_root in source_roots:
            if not isinstance(raw_source_root, str):
                violations.append(f"{language}: naming source_roots entries must be strings")
                continue
            source_root = root / raw_source_root
            if not source_root.is_dir():
                violations.append(f"{language}: missing naming source root {raw_source_root}")
                continue
            for path in _source_files(source_root, language):
                if language == "rust" and "bin" in path.relative_to(source_root).parts:
                    continue
                if language == "python" and path.stem in _IGNORED_PYTHON_STEMS:
                    continue
                leaf_stem = _leaf_stem(path, language)
                if leaf_stem is None or not style.fullmatch(leaf_stem):
                    violations.append(
                        f"{path.relative_to(root)} does not use {language} {_EXPECTED_NAMING[language][0]} naming"
                    )
                    continue
                normalized = _normalise_stem(path, language)
                if language != "python":
                    previous = formal_paths[(language, "source")].get(normalized)
                    if previous is not None:
                        violations.append(
                            f"{language} normalized basename collision: "
                            f"{previous.relative_to(root)} and {path.relative_to(root)}"
                        )
                    formal_paths[(language, "source")][normalized] = path
                source_stems[language].add(normalized)

        # Rust integration tests are part of the formal system's public
        # boundary. Keep their source leaves explicit as well, while Cargo
        # target names remain a separately governed command-level API.
        test_roots = entry.get("test_roots")
        if language == "rust":
            if not isinstance(test_roots, list) or not test_roots:
                violations.append("rust: naming test_roots must be a non-empty list")
                continue
        elif test_roots is None:
            continue
        if not isinstance(test_roots, list):
            violations.append(f"{language}: naming test_roots must be a list")
            continue
        for raw_test_root in test_roots:
            if not isinstance(raw_test_root, str):
                violations.append(f"{language}: naming test_roots entries must be strings")
                continue
            test_root = root / raw_test_root
            if not test_root.is_dir():
                violations.append(f"{language}: missing naming test root {raw_test_root}")
                continue
            for path in _source_files(test_root, language):
                leaf_stem = _leaf_stem(path, language, test=True)
                if leaf_stem is None:
                    violations.append(f"{path.relative_to(root)} must use the {language} '.test' test-leaf suffix")
                    continue
                if not style.fullmatch(leaf_stem):
                    violations.append(
                        f"{path.relative_to(root)} does not use {language} {_EXPECTED_NAMING[language][0]} naming"
                    )
                    continue
                normalized = _normalise_stem(path, language, test=True)
                if language != "python":
                    previous = formal_paths[(language, "test")].get(normalized)
                    if previous is not None:
                        violations.append(
                            f"{language} normalized basename collision: "
                            f"{previous.relative_to(root)} and {path.relative_to(root)}"
                        )
                    formal_paths[(language, "test")][normalized] = path
                source_stems[language].add(normalized)

    python_stems = source_stems.get("python", set())
    for language in ("rust", "typescript"):
        for normalized in sorted(source_stems.get(language, set()) & python_stems):
            path = formal_paths[(language, "source")].get(normalized) or formal_paths[(language, "test")].get(
                normalized
            )
            if path is None:
                continue
            violations.append(
                f"{path.relative_to(root)} reuses Python reference basename {normalized!r}; "
                "formal leaves must use a distinct normalized basename"
            )

    return violations


def _load_rules(rules_path: Path = RULES_DEFAULT) -> dict[str, Any]:
    """Load the commit-time naming rules (hierarchy/ownership)."""
    try:
        value = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to read {rules_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("naming rules must contain a mapping")
    return value


def _staged_paths(root: Path = ROOT) -> list[Path]:
    """Return staged (added/copied/modified/renamed) paths relative to root."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [Path(line) for line in proc.stdout.splitlines() if line.strip()]


def _check_staged_dir_hierarchy(staged: list[Path], rules: dict[str, Any]) -> list[str]:
    """Enforce kebab-case directories and hierarchy/ownership on staged paths."""
    violations: list[str] = []
    systems = rules.get("systems")
    if not isinstance(systems, dict):
        return violations
    for path in staged:
        # Directory segments under every formal system must be kebab-case.
        for sys_dir in FORMAL_SYSTEM_DIRS:
            if path.is_relative_to(sys_dir):
                for segment in path.relative_to(sys_dir).parts[:-1]:
                    if not _DIR_STYLE.fullmatch(segment):
                        violations.append(f"{path}: directory segment {segment!r} is not lowercase kebab-case")
                break
        # Hierarchy / ownership rules per owning system's source root.
        for sys_rules in systems.values():
            src_root_raw = sys_rules.get("src_root")
            if not isinstance(src_root_raw, str):
                continue
            src_root = Path(src_root_raw)
            if not path.is_relative_to(src_root):
                continue
            rel = path.relative_to(src_root)
            rel_parts = rel.parts
            if sys_rules.get("no_root_files") and len(rel_parts) == 1:
                violations.append(f"{path}: loose file under {src_root} — must live in a domain subdirectory")
            allowed = sys_rules.get("allowed_subdirs")
            if isinstance(allowed, list) and len(rel_parts) >= 2 and rel_parts[0] not in allowed:
                violations.append(
                    f"{path}: undeclared subdirectory {rel_parts[0]!r} under {src_root}; allowed: {', '.join(allowed)}"
                )
            ownership = sys_rules.get("ownership")
            if isinstance(ownership, dict) and len(rel_parts) >= 2:
                rule = ownership.get(rel_parts[0])
                if isinstance(rule, dict):
                    stem = rel_parts[-1].rsplit(".", 1)[0]
                    exact = rule.get("exact")
                    prefix = rule.get("prefix")
                    if isinstance(exact, str) and stem != exact:
                        violations.append(f"{path}: leaf must be exactly {exact!r} under {src_root / rel_parts[0]}")
                    elif isinstance(prefix, str) and not stem.startswith(prefix):
                        violations.append(f"{path}: leaf must use prefix {prefix!r} under {src_root / rel_parts[0]}")
            if sys_rules.get("no_bench_in_src") and any("bench" in part for part in rel_parts):
                bench_root = sys_rules.get("bench_root")
                hint = f"move under {bench_root}/" if isinstance(bench_root, str) else "move under bench/"
                violations.append(f"{path}: benchmark source under {src_root} — {hint}")
            break  # only the owning system's src_root matches a given path
    return violations


def check_staged_naming(root: Path = ROOT, rules_path: Path = RULES_DEFAULT) -> list[str]:
    """Return staged naming violations: staged dir/hierarchy rules + full scan."""
    try:
        rules = _load_rules(rules_path)
    except ValueError as exc:
        return [str(exc)]
    staged = _staged_paths(root)
    violations = _check_staged_dir_hierarchy(staged, rules)
    violations.extend(check_system_naming(root))
    return violations


def main() -> int:
    """Run the naming check and print a concise machine-readable result."""
    parser = argparse.ArgumentParser(description="Validate language-native leaf names across the three Praxis systems.")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="commit-time mode: staged dir/hierarchy rules plus the full scan",
    )
    args = parser.parse_args()
    if args.staged:
        violations = check_staged_naming()
        label = "STAGED_NAMING"
    else:
        violations = check_system_naming()
        label = "SYSTEM_NAMING"
    if violations:
        print(f"{label}: FAIL")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print(f"{label}: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
