#!/usr/bin/env python3
"""Run Rust kernel integration targets as bounded, parallel domain slices."""

from __future__ import annotations

import argparse
import math
import os
import signal
import subprocess
import sys
import time
import tomllib
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "systems" / "rust-kernel-engine" / "l1-kernel-rs" / "Cargo.toml"
TEST_ROOT = MANIFEST.parent / "tests"
DOMAINS = (
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
)


@dataclass(frozen=True)
class TargetResult:
    """Capture one isolated Cargo target invocation."""

    domain: str
    target: str
    command: tuple[str, ...]
    returncode: int
    output: str
    duration_seconds: float
    timed_out: bool = False


def _targets_by_domain() -> dict[str, tuple[str, ...]]:
    """Read explicit Cargo targets and group them by test domain."""
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    grouped: dict[str, list[str]] = {domain: [] for domain in DOMAINS}
    for target in manifest.get("test", []):
        path_value = target.get("path")
        name = target.get("name")
        if not isinstance(path_value, str) or not isinstance(name, str):
            raise ValueError("every Cargo [[test]] entry needs string name and path")
        path = MANIFEST.parent / path_value
        relative = path.relative_to(TEST_ROOT)
        if len(relative.parts) != 2 or relative.parts[0] not in grouped:
            raise ValueError(f"Cargo test target is outside a declared domain: {path_value}")
        if not path.is_file():
            raise ValueError(f"Cargo test target points to a missing file: {path_value}")
        grouped[relative.parts[0]].append(name)
    return {domain: tuple(targets) for domain, targets in grouped.items()}


def _selected_domains(requested: Sequence[str] | None, grouped: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Return requested domains in declaration order, rejecting unknown names."""
    if not requested:
        return DOMAINS
    unknown = sorted(set(requested) - set(grouped))
    if unknown:
        raise ValueError(f"unknown Rust test domain(s): {', '.join(unknown)}")
    return tuple(domain for domain in DOMAINS if domain in requested)


def _decode_output(output: str | bytes | None) -> str:
    """Normalize subprocess output across text and mocked process APIs."""
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """Terminate a timed-out Cargo process and every child in its session."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        return

    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_target(domain: str, target: str, timeout_seconds: float) -> TargetResult:
    """Run one Cargo integration target with a bounded process lifetime."""
    command = (
        "cargo",
        "test",
        "--manifest-path",
        str(MANIFEST),
        "--test",
        target,
    )
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        return TargetResult(
            domain,
            target,
            command,
            127,
            f"unable to start Cargo target: {error}",
            time.monotonic() - started,
        )

    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        output, _ = process.communicate()
        elapsed = time.monotonic() - started
        detail = _decode_output(output).rstrip()
        timeout_note = f"target timed out after {timeout_seconds:g}s; process group terminated"
        combined = f"{detail}\n{timeout_note}" if detail else timeout_note
        return TargetResult(domain, target, command, 124, combined, elapsed, timed_out=True)

    return TargetResult(
        domain,
        target,
        command,
        process.returncode,
        _decode_output(output),
        time.monotonic() - started,
    )


def _run_selected(
    grouped: dict[str, tuple[str, ...]],
    domains: Sequence[str],
    jobs: int,
    timeout_seconds: float,
) -> list[TargetResult]:
    """Run selected targets with bounded parallelism and stable reporting order."""
    work = [(domain, target) for domain in domains for target in grouped[domain]]
    results: dict[tuple[str, str], TargetResult] = {}
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {
            executor.submit(_run_target, domain, target, timeout_seconds): (domain, target) for domain, target in work
        }
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
    return [results[(domain, target)] for domain, target in work]


def _print_listing(grouped: dict[str, tuple[str, ...]], domains: Sequence[str]) -> None:
    """Print the selected domain and target inventory."""
    for domain in domains:
        targets = grouped[domain]
        print(f"{domain}: {len(targets)} target(s)")
        for target in targets:
            print(f"  - {target}")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the bounded domain-runner command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--domain",
        action="append",
        dest="domains",
        choices=DOMAINS,
        help="run only this domain; repeat for multiple domains",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, min(4, os.cpu_count() or 1)),
        help="maximum concurrent Cargo target processes (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        metavar="SECONDS",
        help="maximum runtime for each target before terminating its process group (default: %(default)s)",
    )
    parser.add_argument("--list", action="store_true", help="list selected domains and targets")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running targets")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="include passing target output; failures always include their captured output",
    )
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a finite value greater than zero")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected Rust integration targets and report every result."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        grouped = _targets_by_domain()
        domains = _selected_domains(args.domains, grouped)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        print(f"rust test domain configuration error: {error}", file=sys.stderr)
        return 2

    if args.list:
        _print_listing(grouped, domains)
        return 0

    work = [(domain, target) for domain in domains for target in grouped[domain]]
    if args.dry_run:
        for _, target in work:
            print(f"cargo test --manifest-path {MANIFEST} --test {target}")
        return 0

    results = _run_selected(grouped, domains, args.jobs, args.timeout)
    failures = 0
    for result in results:
        status = "TIMEOUT" if result.timed_out else ("PASS" if result.returncode == 0 else "FAIL")
        print(f"\n[{status}] {result.domain}/{result.target} ({result.duration_seconds:.2f}s)")
        if result.returncode != 0:
            failures += 1
        if args.verbose or result.returncode != 0:
            print(result.output.rstrip())
    print(f"\nRust test slices: {len(results) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
