"""Benchmark the L2 protocol envelope and JSONL host reference path."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "py"))

from perf_harness import (  # noqa: E402
    PERF_HARNESS_SAMPLE_ROUNDS,
    PERF_HARNESS_WARMUP_ROUNDS,
    run_suite,
    write_json,
)

from l2.protocol import KIND_COMMAND, encode_message, make_message  # noqa: E402
from l2.protocol.envelope import decode_message  # noqa: E402
from l2.protocol.host import ProtocolHost  # noqa: E402


def _encode_decode(iterations: int) -> None:
    """Round-trip canonical envelope encoding and validation."""
    for index in range(iterations):
        line = encode_message(make_message("bench", index, KIND_COMMAND, {"name": "lang"}))
        message, error = decode_message(line)
        if error or message is None:
            raise RuntimeError(error or "protocol decode returned no message")


def _host_commands(iterations: int) -> None:
    """Dispatch command envelopes through one in-process protocol host."""
    host = ProtocolHost()
    for index in range(iterations):
        line = encode_message(make_message("bench", index, KIND_COMMAND, {"name": "lang"}))
        output = host.handle(line)
        if len(output) != 2 or not output[0]["payload"].get("success"):
            raise RuntimeError("protocol host command failed")


def run(iterations: int, warmups: int, samples: int) -> dict[str, Any]:
    """Run protocol cases and return a schema-versioned benchmark document."""
    return run_suite(
        [
            ("l2.protocol.encode_decode", _encode_decode, iterations),
            ("l2.protocol.host_command", _host_commands, iterations),
        ],
        warmups=warmups,
        samples=samples,
    )


def main() -> int:
    """Parse options, run protocol benchmarks, and print a compact report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1_000)
    parser.add_argument("--warmups", type=int, default=PERF_HARNESS_WARMUP_ROUNDS)
    parser.add_argument("--samples", type=int, default=PERF_HARNESS_SAMPLE_ROUNDS)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()
    document = run(max(1, args.iterations), max(0, args.warmups), max(1, args.samples))
    print("L2 protocol benchmark")
    for benchmark in document["benchmarks"]:
        summary = benchmark["summary"]
        print(f"{benchmark['name']}.ops_per_sec: {summary['ops_per_sec']:.3f}")
        print(f"{benchmark['name']}.latency_p95_ms: {summary['latency_p95_ms']:.6f}")
    if args.json:
        write_json(args.json, document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
