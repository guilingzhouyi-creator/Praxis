"""Generate LLM-friendly documentation indexes (llms.txt pattern, like Hermes).

Outputs, under docs/architecture/:
  llms.txt       — curated index: every doc page with a one-line description
  llms-full.txt  — all docs concatenated into one markdown file (one-shot
                   ingestion for agents)

Regenerate after doc changes:  python scripts/py/gen-llms-txt.py

Index lines that embed counts (params constants, routes, commands, tools,
SoC components) are composed at runtime from the live codebase
(``gen_doc_stats.collect_stats()`` / file & config scans) so the CI
regenerate+diff gate actually detects code-driven drift — a hardcoded
count would never change and the gate would stay green on stale docs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from collect_stats import (  # noqa: E402
    code_registered_command_count,
    collect_stats,
    count_files,
    yaml_command_count,
)

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
DOCS = ROOT / "docs" / "architecture"
OUT_INDEX = DOCS / "llms.txt"
OUT_FULL = DOCS / "llms-full.txt"


def _l1_kernel_desc() -> str:
    """Compose the l1-kernel index description with live params counts."""
    stats = collect_stats()
    return (
        "Kernel: process table, sync, event bus, constitution, GateChain G1-G5, "
        f"port abstractions, {stats['params_constants']:,} params constants across "
        f"{stats['params_modules']} modules"
    )


def _l2_shell_desc() -> str:
    """Compose the l2-shell index description with live command counts."""
    return (
        f"Shell: {yaml_command_count()} YAML commands + "
        f"{code_registered_command_count()} code-registered, i18n, completer, "
        "agent selector, dict-in/dict-out handler contract"
    )


def _l3_tools_desc() -> str:
    """Compose the l3-tools index description with the live tool count."""
    return (
        f"Tool layer: {count_files('l3/tools')} implementations by domain + "
        "tool system (spec/registry/policy/9-step pipeline)"
    )


def _l3_cell_os_desc() -> str:
    """Compose the l3-cell-os index description with the live component count."""
    return (
        f"Cell runtime: {count_files('l3/cell/components')} SoC components "
        "(I-Cache, MMU, PMU, Watchdog, Interrupt, Rollback, Permission...) "
        "+ boot/install/lifecycle/wiring"
    )


def _l4_bridge_desc() -> str:
    """Compose the l4-bridge index description with the live route count."""
    stats = collect_stats()
    return (
        f"Bridge: {stats['routes']} routes, API gateway, LLM engine, "
        "SSE/WS/RPC channels, auth/fs contracts, sandbox, with message/auth sequences"
    )


# Index pages whose description embeds counts — composed from the live
# codebase instead of the static MANIFEST text (drift-detectable).
DYNAMIC_DESC = {
    "l1-kernel.md": _l1_kernel_desc,
    "l2-shell.md": _l2_shell_desc,
    "l3-tools.md": _l3_tools_desc,
    "l3-cell-os.md": _l3_cell_os_desc,
    "l4-bridge.md": _l4_bridge_desc,
}

# (filename, one-line description) — keep in reading order. Entries listed in
# DYNAMIC_DESC ignore the description here; it is kept as a readable fallback.
MANIFEST = [
    (
        "README.md",
        "Layer reference index: navigation, numbers snapshot, system overview diagram, reading paths, main data flows, design principles",
    ),
    (
        "l1-kernel.md",
        "Kernel: process table, sync, event bus, constitution, GateChain G1-G5, port abstractions (counts composed at runtime)",
    ),
    (
        "l2-shell.md",
        "Shell: YAML + code-registered commands, i18n, completer, agent selector, dict-in/dict-out handler contract",
    ),
    (
        "l3-card-lifecycle.md",
        "Card lifecycle: produce (L3A cardwrite) -> execute (plan/agents/tools) -> approve (GateChain/approval gate) -> complete -> R4 archive, with state diagram",
    ),
    (
        "l3-memory.md",
        "Memory: 4 rings + side-channels (Mer symbolization, R5 graph, user profile) + system-prompt injection, with Mer pipeline diagram",
    ),
    (
        "l3a-central.md",
        "L3A decision layer: sessions, l3a_ask clarification, cardwrite, profile consumption, session/ask state machines, session contract endpoints",
    ),
    (
        "l3-tools.md",
        "Tool layer: implementations by domain + tool system (spec/registry/policy/9-step pipeline)",
    ),
    (
        "security-evidence.md",
        "Security evidence chain: attack-posture bypass audit, tamper-evident chain + verdicts, metric bridge + bypass API",
    ),
    (
        "l3-cell-os.md",
        "Cell runtime: SoC components (I-Cache, MMU, PMU, Watchdog, Interrupt, Rollback, Permission...) + boot/install/lifecycle/wiring",
    ),
    (
        "l3-scheduler.md",
        "Scheduler: 5D matrix (route/pool/time/rate/scope) + ACB + safety layers (loop detectors, sequence monitor, think registry)",
    ),
    (
        "l3-convention.md",
        "Cross-cell deliberation: orchestrator -> answer sessions -> aggregator -> supplements -> report, with flow diagram",
    ),
    (
        "l4-bridge.md",
        "Bridge: routes, API gateway, LLM engine, SSE/WS/RPC channels, auth/fs contracts, sandbox, with message/auth sequences",
    ),
    ("l5-user.md", "User layer: CLI entry, CLI/TUI/desktop contract tiers"),
    (
        "cross-cutting.md",
        "Cross-cutting: governance, event flow, system-prompt injection switches, session anti-blowup, testing/QA, skills lifecycle, collaboration discipline",
    ),
]


def main() -> None:
    # ── llms.txt (index) ──
    lines = [
        "# Praxis Agent OS — Architecture Docs",
        "",
        "Five-layer Agent Operating System. Entry point:",
        "docs/architecture/README.md (navigation + generated numbers + design principles).",
        "",
        "## Index",
        "",
    ]
    for fname, desc in MANIFEST:
        factory = DYNAMIC_DESC.get(fname)
        if factory is not None:
            desc = factory()
        lines.append(f"- [{fname}]({fname}): {desc}")
    lines.append("")
    lines.append("> Generated by scripts/py/gen-llms-txt.py — regenerate after doc changes.")
    OUT_INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ── llms-full.txt (concatenation for one-shot ingestion) ──
    chunks = [
        "# Praxis Agent OS — Full Architecture Documentation\n",
        "> Concatenated for one-shot LLM ingestion. Generated by",
        "> scripts/py/gen-llms-txt.py; regenerate after doc changes.\n",
    ]
    for fname, _desc in MANIFEST:
        src = DOCS / fname
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        # strip yaml-ish fences noise? keep as-is; just delimit pages
        chunks.append(f"\n\n---\n\n# Source: {fname}\n\n")
        chunks.append(text)
    OUT_FULL.write_text("".join(chunks), encoding="utf-8")

    print(f"wrote {OUT_INDEX.relative_to(ROOT)} ({OUT_INDEX.stat().st_size} bytes)")
    print(f"wrote {OUT_FULL.relative_to(ROOT)} ({OUT_FULL.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
