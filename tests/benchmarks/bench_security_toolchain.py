"""Benchmark the security/toolchain cross-links covered by the unified metrics contract."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from statistics import median

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from l3.memory.memory_graph import MemoryGraph  # noqa: E402
from l3.services.todo_tracker import TodoTracker  # noqa: E402
from l3.tool_system.dvg import DvgGraph, get_dvg  # noqa: E402
from l3.tool_system.security_evidence import SecurityEvidence  # noqa: E402
from l3.tool_system.tool_registry import ToolRegistry  # noqa: E402
from l3.tool_system.tool_spec import ToolSpec  # noqa: E402


class _RelationEngine:
    """Deterministic semantic relation engine for the microbenchmark."""

    def generate(self, prompt: str, **kwargs) -> dict:
        """Return one stable relation without model or network latency."""
        return {"content": "depends_on"}


def _ops_per_second(operation, iterations: int, rounds: int) -> float:
    """Return the median operations per second for a bounded operation."""
    values: list[float] = []
    for _ in range(rounds):
        started = time.perf_counter()
        operation(iterations)
        elapsed = time.perf_counter() - started
        values.append(iterations / elapsed if elapsed else 0.0)
    return float(median(values))


def _bench_dvg(iterations: int, rounds: int) -> dict[str, float]:
    """Measure DVG plan calculation and dynamic registry registration."""

    def plans(count: int) -> None:
        graph = DvgGraph()
        graph.register_tool_deps("dependency", [])
        graph.register_tool_deps("root", ["dependency"])
        for _ in range(count):
            graph.execution_plan("root")

    def registrations(count: int) -> None:
        shared = get_dvg()
        shared.clear()
        shared.register_tool_deps("bench-dependency", [])
        registry = ToolRegistry()
        for index in range(count):
            name = f"bench-tool-{index}"
            spec = ToolSpec(name=name, description="bench", category="bench", ring="ring_1", danger=0)
            registry.register_tool_with_deps(spec, ["bench-dependency"], source="benchmark")

    graph = DvgGraph()
    graph.register_tool_deps("bench-dependency", [])
    return {
        "dvg.plan_ops_per_sec": _ops_per_second(plans, iterations, rounds),
        "tool_registry.register_ops_per_sec": _ops_per_second(registrations, iterations, rounds),
    }


def _bench_todo(iterations: int, rounds: int) -> dict[str, float]:
    """Measure JSON persistence plus register-backed TODO index updates."""

    def persist(count: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tracker = TodoTracker(state_path=os.path.join(directory, "todo.json"), executor_id="bench-executor")
            for index in range(count):
                tracker.update(f"task-{index}", "pending")

    return {"todo.persist_ops_per_sec": _ops_per_second(persist, iterations, rounds)}


def _bench_r5(iterations: int, rounds: int) -> dict[str, float]:
    """Measure rule-edge writes and bounded hybrid semantic extraction."""

    def rules(count: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = MemoryGraph(db_path=os.path.join(directory, "graph.db"), enabled=True)
            recent: list[dict] = []
            for index in range(count):
                entry_id = f"entry-{index}"
                graph.remember_hook(entry_id, "bench-agent", "note", "bench-cell", recent[-1:], created_by="benchmark")
                recent.append(
                    {"id": entry_id, "entry_type": "note", "agent_id": "bench-agent", "cell_id": "bench-cell"}
                )

    def semantic(count: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = MemoryGraph(db_path=os.path.join(directory, "semantic.db"), enabled=True)
            graph.set_edge_mode("rules")
            graph.set_edge_mode("hybrid")
            engine = _RelationEngine()
            for index in range(count):
                graph.extract_semantic_edges(
                    [
                        {"id": f"a-{index}", "entry_type": "note", "content": "decision"},
                        {"id": f"b-{index}", "entry_type": "note", "content": "basis"},
                    ],
                    engine=engine,
                    created_by="benchmark",
                )

    return {
        "r5.rule_edges_ops_per_sec": _ops_per_second(rules, iterations, rounds),
        "r5.semantic_pairs_ops_per_sec": _ops_per_second(semantic, iterations, rounds),
    }


def _bench_evidence(iterations: int, rounds: int) -> dict[str, float]:
    """Measure append-only evidence writes and fixity verification."""

    def records(count: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            collector = SecurityEvidence(path=os.path.join(directory, "evidence.jsonl"))
            for index in range(count):
                collector.record("benchmark", gate="metrics", target=f"tool-{index}", source="benchmark")

    def verify(count: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            collector = SecurityEvidence(path=os.path.join(directory, "evidence.jsonl"))
            chain_id = collector.record("benchmark", gate="metrics", target="tool", source="benchmark")
            for _ in range(count):
                collector.verify_chain(chain_id)

    return {
        "security_evidence.record_ops_per_sec": _ops_per_second(records, iterations, rounds),
        "security_evidence.verify_ops_per_sec": _ops_per_second(verify, iterations, rounds),
    }


def run(iterations: int, rounds: int) -> dict[str, float]:
    """Run each security/toolchain microbenchmark and return ops/sec metrics."""
    result: dict[str, float] = {}
    result.update(_bench_dvg(iterations, rounds))
    result.update(_bench_todo(iterations, rounds))
    result.update(_bench_r5(iterations, rounds))
    result.update(_bench_evidence(iterations, rounds))
    return result


def main() -> int:
    """Parse options and print the benchmark report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    result = run(max(1, args.iterations), max(1, args.rounds))
    print("Security toolchain benchmark")
    for key, value in sorted(result.items()):
        print(f"{key}: {value:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
