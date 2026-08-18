"""Benchmark L3A session compression ratio and throughput (3.1, G7).

Run with: python tests/benchmarks/bench_compression.py. Measures the
decision-layer five-level compression pipeline's compression ratio
(before/after token counts), folded-message and dedup counts, and
compressions-per-second on synthetic sessions.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from l3.cell.peers.l3a.session import Message, Session  # noqa: E402


def _build_session(n_messages: int) -> Session:
    """Build a synthetic session with n user/assistant message pairs."""
    s = Session.create(title="bench-compression")
    for i in range(n_messages):
        s.history.append(
            Message(id=f"u{i}", role="user", content=f"user message number {i} with enough text to matter")
        )
        s.history.append(Message(id=f"a{i}", role="assistant", content=f"assistant reply {i} " + "x" * 80))
    return s


def _run_once(n_messages: int, keep_last: int) -> dict[str, float]:
    """Compress one synthetic session and return its metrics."""
    s = _build_session(n_messages)
    start = time.perf_counter()
    r = s.compress(keep_last=keep_last)
    elapsed = time.perf_counter() - start
    return {
        "elapsed": elapsed,
        "compressed": float(r.get("compressed", 0)),
        "deduplicated": float(r.get("deduplicated", 0)),
        "ratio": float(r.get("compression_ratio", 0.0)),
        "before_tokens": float(r.get("before_tokens", 0)),
        "after_tokens": float(r.get("after_tokens", 0)),
    }


def run(n_messages: int, keep_last: int, rounds: int) -> dict[str, float]:
    """Report median compression ratio and throughput across rounds."""
    ratios: list[float] = []
    elapsed: list[float] = []
    compressed: list[float] = []
    dedup: list[float] = []
    before_tokens: list[float] = []
    after_tokens: list[float] = []
    for _ in range(rounds):
        m = _run_once(n_messages, keep_last)
        ratios.append(m["ratio"])
        elapsed.append(m["elapsed"])
        compressed.append(m["compressed"])
        dedup.append(m["deduplicated"])
        before_tokens.append(m["before_tokens"])
        after_tokens.append(m["after_tokens"])
    median_elapsed = statistics.median(elapsed)
    return {
        "messages": float(n_messages),
        "keep_last": float(keep_last),
        "compression_ratio": round(statistics.median(ratios), 3),
        "compressed_msgs": statistics.median(compressed),
        "dedup_msgs": statistics.median(dedup),
        "before_tokens": statistics.median(before_tokens),
        "after_tokens": statistics.median(after_tokens),
        "compress_ops_per_sec": round(n_messages / median_elapsed, 1) if median_elapsed else 0.0,
    }


def main() -> int:
    """Parse benchmark options and print a compact performance report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=int, default=200)
    parser.add_argument("--keep-last", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()
    result = run(args.messages, args.keep_last, args.rounds)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
    print("L3A compression benchmark")
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
