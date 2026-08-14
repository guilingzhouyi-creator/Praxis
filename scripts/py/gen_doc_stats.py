"""Generate architecture-doc statistics from the live codebase.

Run before updating docs/architecture/README.md (the numbers snapshot):

    python scripts/py/gen_doc_stats.py

Prints the stats table used by README.md. Never hand-edit the numbers —
they drift; regenerate instead. The counting logic lives in ``collect_stats``
(``scripts/py/collect_stats.py``) — the single source of truth shared by
``gen_llms_txt.py`` and ``check_doc_stats.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from collect_stats import collect_stats, health_scores  # noqa: E402


def format_stats(stats: dict) -> str:
    """Render the stats table exactly as README documents it."""
    lines = ["=" * 62, "Praxis architecture stats (generated - do not hand-edit)", "=" * 62]
    for name, (n, total) in stats["layers"].items():
        lines.append(f"  {name:<14} {n:>4} files  {total:>7} lines")
    lines.append("  ---")
    for name, (n, total) in stats["sub"].items():
        lines.append(f"  {name:<14} {n:>4} files  {total:>7} lines")
    lines.append("  ---")
    lines.append(f"  API routes:      {stats['routes']}")
    lines.append(f"  Params modules:  {stats['params_modules']}")
    lines.append(f"  Params constants:{stats['params_constants']}")
    domain_str = ", ".join(f"{d}={n}" for d, n in stats["domains"].items())
    lines.append(f"  Route domains:   {domain_str}")
    lines.append("  ---")
    lines.append(f"  Test files:      {stats['test_files']}")
    lines.append(f"  Test cases:      {stats['test_cases']}")
    lines.append(f"  Long functions:  {stats['long_functions']} (>200 lines)")
    lines.append(f"  Comment ratio:   {stats['comment_ratio']:.4f}")
    lines.append(f"  3rd-party deps:  {', '.join(stats['third_party_imports']) or 'none'}")
    h = health_scores(stats)
    scores = "  ".join(f"{k}={v:.2f}" for k, v in h["scores"].items())
    lines.append(f"  Health:          {scores}")
    lines.append(f"  Health overall:  {h['overall']:.3f} (grade {h['grade']})")
    lines.append("=" * 62)
    return "\n".join(lines)


def main() -> None:
    print(format_stats(collect_stats()))


if __name__ == "__main__":
    main()
