#!/usr/bin/env python3
"""Test runner — runs the test suite via pytest in per-layer slices.

Slices group tests by layer (matching the architecture), with slow hotspots
split out so a failure is attributable to one layer and the fast paths are
never blocked by the slow ones:

    infra → l1 → l2 → l3-fast → l3-mid → l3-slow → l4-fast → l4-lsp
         → l5 → integration → benchmarks

Usage:
  python tests/runner.py                # run all slices in dependency order
  python tests/runner.py --once         # whole suite in ONE pytest process (fastest)
  python tests/runner.py --keep-going   # full run, report every failing slice
  python tests/runner.py --slice l3-fast # run one slice only
  python tests/runner.py --list-slices  # print slice names
  python tests/runner.py --batch 1|2    # legacy: batch 1 = all but slow, batch 2 = slow
  python tests/runner.py --maxfail 5    # forward --maxfail=N to pytest (any mode)
  python tests/runner.py <pattern>      # single file/pattern (legacy)
"""

from __future__ import annotations

import os
import subprocess
import sys

# ── Slice table ──
# Key = slice name (layer + hotspot suffix); value = list of directory paths
# (or explicit file paths) under tests/. Directory paths automatically cover
# every test_*.py inside — new files join their layer slice with no edit.
SLICES: dict[str, list[str]] = {
    # Gate files first: fail fast on boundary/params violations.
    "infra": ["tests/infra"],
    # Kernel / shell.
    "l1": ["tests/l1"],
    "l2": ["tests/l2"],
    # L3 fast paths (sub-second to ~5s per dir) + l3 top-level stragglers.
    "l3-fast": [
        "tests/l3/cell",
        "tests/l3/agent",
        "tests/l3/agent_terminal",
        "tests/l3/tools",
        "tests/l3/card",
        "tests/l3/bus",
        "tests/l3/scheduler",
        "tests/l3/l3a",
        "tests/l3/boot",
        "tests/l3/config",
        "tests/l3/subagent",
        "tests/l3/discussion",
        "tests/l3/identity",
        "tests/l3/error_bus",
        "tests/l3/session",
        # l3 top-level test files (not under any subdir).
        "tests/l3/test_approval_gate.py",
        "tests/l3/test_approval_policy.py",
        "tests/l3/test_archive_orchestrator.py",
        "tests/l3/test_base.py",
        "tests/l3/test_i18n_l3_surface.py",
        "tests/l3/test_net_client.py",
        "tests/l3/test_persistable.py",
        "tests/l3/test_pool.py",
        "tests/l3/test_prompt_engine.py",
        "tests/l3/test_security_evidence.py",
        "tests/l3/test_tool_approval.py",
        "tests/l3/test_tool_ring.py",
    ],
    # L3 medium: services (~47s) + tool_system (~91s) — kept out of l3-fast
    # so a slow suite does not hold up the fast layer check.
    "l3-mid": ["tests/l3/services", "tests/l3/tool_system"],
    # L3 slow: memory directory (>270s incl. r4_agent distillation suite).
    # Isolated so the rest of the suite never waits on it.
    "l3-slow": ["tests/l3/memory"],
    # L4 fast paths + l4 top-level stragglers.
    "l4-fast": [
        "tests/l4/api_handlers",
        "tests/l4/sandbox",
        "tests/l4/api",
        "tests/l4/adapters",
        "tests/l4/auth",
        "tests/l4/vault",
        "tests/l4/search",
        "tests/l4/rpc",
        "tests/l4/mcp",
        "tests/l4/llm_worker",
        "tests/l4/llm",
        "tests/l4/misc",
        # l4 top-level test files (not under any subdir).
        "tests/l4/test_api_auth.py",
        "tests/l4/test_api_endpoints.py",
        "tests/l4/test_api_fs.py",
        "tests/l4/test_api_gateway.py",
        "tests/l4/test_api_gateway_integration.py",
        "tests/l4/test_api_graph.py",
        "tests/l4/test_api_handlers_cards.py",
        "tests/l4/test_api_handlers_cluster.py",
        "tests/l4/test_api_handlers_config.py",
        "tests/l4/test_api_l3a_sessions.py",
        "tests/l4/test_api_middleware_integration.py",
        "tests/l4/test_api_profile.py",
        "tests/l4/test_api_routes.py",
        "tests/l4/test_auth_session.py",
        "tests/l4/test_ci.py",
        "tests/l4/test_ci_review.py",
        "tests/l4/test_credential_vault.py",
        "tests/l4/test_cron_scheduler.py",
        "tests/l4/test_effort_tiers.py",
        "tests/l4/test_git.py",
        "tests/l4/test_llm.py",
        "tests/l4/test_lsp_manager.py",
        "tests/l4/test_mcp_bridge.py",
        "tests/l4/test_mcp_hooks.py",
        "tests/l4/test_misc.py",
        "tests/l4/test_model_spec_panel.py",
        "tests/l4/test_model_strategy.py",
        "tests/l4/test_model_strategy_phase.py",
        "tests/l4/test_notify.py",
        "tests/l4/test_ops_console.py",
        "tests/l4/test_peer_strategy.py",
        "tests/l4/test_rpc_server.py",
        "tests/l4/test_sandbox.py",
        "tests/l4/test_sandbox_integration.py",
        "tests/l4/test_search_engine.py",
        "tests/l4/test_sse_bridge.py",
        "tests/l4/test_sse_bridge_integration.py",
        "tests/l4/test_subscriptions.py",
        "tests/l4/test_supervisor.py",
        "tests/l4/test_user_session.py",
        "tests/l4/test_ws_bridge.py",
    ],
    # L4 LSP stdio suite (~41s) — independent slice.
    "l4-lsp": ["tests/l4/lsp"],
    # User layer / integration / benchmarks.
    "l5": ["tests/l5"],
    "integration": ["tests/integration"],
    "benchmarks": ["tests/benchmarks"],
}

# Dependency order for a full run (fail-fast first, slow hotspots last).
FULL_ORDER = [
    "infra",
    "l1",
    "l2",
    "l3-fast",
    "l3-mid",
    "l3-slow",
    "l4-fast",
    "l4-lsp",
    "l5",
    "integration",
    "benchmarks",
]

# Legacy batch aliases (backward compatible with `--batch 1|2`):
# batch 1 = everything except the slow hotspot; batch 2 = the slow hotspot.
BATCH_1 = [s for s in FULL_ORDER if s != "l3-slow"]
BATCH_2 = ["l3-slow"]


def run_targets(
    targets: list[str],
    label: str,
    parallel: bool = False,
    no_xdist: bool = False,
    maxfail: int | None = None,
) -> int:
    """Run pytest over *targets*; return the process exit code.

    ``no_xdist`` disables the pyproject ``addopts`` (``-n auto --dist
    loadfile``) by overriding ``-o addopts=`` — xdist startup is very slow
    under WSL, so local slice runs default to serial there.
    ``maxfail`` is forwarded as ``--maxfail=N`` (CI contract: the flag must
    not be silently dropped).
    """
    cmd = [sys.executable, "-m", "pytest"]
    if parallel:
        cmd += ["-n", "auto", "--dist", "loadfile"]
    if no_xdist:
        cmd += ["-o", "addopts="]
    if maxfail is not None:
        cmd += [f"--maxfail={maxfail}"]
    cmd += targets + ["-v", "--tb=short", "-q"]
    print(f"\n{'=' * 60}")
    print(f"  Slice: {label} ({len(targets)} target dir(s))")
    print(f"{'=' * 60}")
    r = subprocess.run(cmd, cwd=os.path.join(os.path.dirname(__file__), ".."))
    if r.returncode != 0:
        print(f"  FAILED: {label} (exit {r.returncode})")
    return r.returncode


def run_slice(name: str, parallel: bool = False, no_xdist: bool = False, maxfail: int | None = None) -> int:
    """Run one named slice; unknown names print the slice list and return 2."""
    if name not in SLICES:
        print(f"unknown slice: {name!r} — available: {', '.join(SLICES)}", file=sys.stderr)
        return 2
    return run_targets(SLICES[name], name, parallel=parallel, no_xdist=no_xdist, maxfail=maxfail)


def _run_legacy_batch(sel: str, parallel: bool, no_xdist: bool, maxfail: int | None) -> int:
    """Run a legacy batch (1 = all but slow, 2 = slow) sequentially."""
    names = BATCH_1 if sel == "1" else BATCH_2 if sel == "2" else None
    if names is None:
        print("--batch expects 1 or 2", file=sys.stderr)
        return 2
    failed: list[str] = []
    for name in names:
        code = run_slice(name, parallel=parallel, no_xdist=no_xdist, maxfail=maxfail)
        if code != 0:
            failed.append(name)
    if failed:
        print(f"\nFAILED slices: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def _run_full(parallel: bool, no_xdist: bool, maxfail: int | None, keep_going: bool) -> int:
    """Run every slice in dependency order.

    Default: stop at the first failure (backward compatible). With
    ``keep_going`` run every slice, report all failures, and exit non-zero
    only if any failed — CI then sees the full failure set in one run.
    """
    failed: list[str] = []
    for name in FULL_ORDER:
        code = run_slice(name, parallel=parallel, no_xdist=no_xdist, maxfail=maxfail)
        if code != 0:
            failed.append(name)
            if not keep_going:
                return code
    if failed:
        print(f"\nFAILED slices: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def _run_once(parallel: bool, no_xdist: bool, maxfail: int | None) -> int:
    """Run the whole suite as ONE pytest process (fastest full path).

    Collects every slice target into a single invocation — avoids re-spawning
    the xdist worker pool per slice (the dominant wall-time cost under WSL:
    a per-slice run of ``infra`` alone measured 54.75s vs 41.6s for the
    complete suite in one process).
    """
    targets: list[str] = []
    for name in FULL_ORDER:
        targets.extend(SLICES[name])
    return run_targets(targets, "all (one process)", parallel=parallel, no_xdist=no_xdist, maxfail=maxfail)


def _run_slice_arg(argv: list[str], parallel: bool, no_xdist: bool, maxfail: int | None) -> int:
    """Handle ``--slice <name>``; missing name prints usage and returns 2."""
    idx = argv.index("--slice")
    if idx + 1 < len(argv):
        return run_slice(argv[idx + 1], parallel=parallel, no_xdist=no_xdist, maxfail=maxfail)
    print("--slice requires a slice name (see --list-slices)", file=sys.stderr)
    return 2


def _run_batch_arg(argv: list[str], parallel: bool, no_xdist: bool, maxfail: int | None) -> int:
    """Handle ``--batch <1|2>``; missing selector returns 2."""
    idx = argv.index("--batch")
    if idx + 1 < len(argv):
        return _run_legacy_batch(argv[idx + 1], parallel, no_xdist, maxfail)
    return 2


_KNOWN_FLAGS = (
    "--list-slices",
    "--parallel",
    "--no-xdist",
    "--slice",
    "--batch",
    "--maxfail",
    "--keep-going",
    "--once",
)


def main() -> int:  # noqa: PLR0911 — one return per CLI dispatch branch
    """CLI entry: slices, legacy batches, full runs, or a single pattern.

    Unknown ``--*`` flags are rejected loudly — they used to be silently
    dropped (e.g. CI's ``--maxfail=5``), hiding configuration errors.
    """
    argv = sys.argv[1:]

    if "--list-slices" in argv:
        for name in FULL_ORDER:
            print(f"{name:<12} {len(SLICES[name])} target(s)")
        return 0

    parallel = "--parallel" in argv
    no_xdist = "--no-xdist" in argv
    keep_going = "--keep-going" in argv
    once = "--once" in argv

    # Maxfail: accept "--maxfail N" or "--maxfail=N"; validate the value.
    maxfail: int | None = None
    for i, a in enumerate(argv):
        if a == "--maxfail":
            if i + 1 < len(argv) and argv[i + 1].lstrip("-").isdigit():
                maxfail = int(argv[i + 1])
            else:
                print("--maxfail requires an integer N", file=sys.stderr)
                return 2
        elif a.startswith("--maxfail="):
            val = a.split("=", 1)[1]
            if not val.isdigit():
                print(f"invalid --maxfail value: {val!r}", file=sys.stderr)
                return 2
            maxfail = int(val)

    # Reject unknown flags instead of silently dropping them.
    for a in argv:
        if a.startswith("--") and a.split("=", 1)[0] not in _KNOWN_FLAGS:
            print(f"unknown flag: {a!r} (see docstring for supported flags)", file=sys.stderr)
            return 2

    if "--slice" in argv:
        return _run_slice_arg(argv, parallel, no_xdist, maxfail)
    if "--batch" in argv:
        return _run_batch_arg(argv, parallel, no_xdist, maxfail)
    if once:
        return _run_once(parallel, no_xdist, maxfail)

    pattern = [a for a in argv if not a.startswith("--")]
    if pattern:
        return run_targets([pattern[0]], pattern[0], parallel=parallel, no_xdist=no_xdist, maxfail=maxfail)

    return _run_full(parallel, no_xdist, maxfail, keep_going)


if __name__ == "__main__":
    sys.exit(main())
