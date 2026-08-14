"""PARALLEL_ALL card execution across multiple peer agents.

A PARALLEL_ALL card fans steps out to several agents concurrently; every
agent's step must complete and the results must aggregate. Uses a
deterministic LLM stub so think steps measure execution, not latency
(same pattern as tests/benchmarks/bench_card.py).
"""

from __future__ import annotations

import time

import pytest

from l3.card.models import Card, CardMode, Phase, PhaseMode, Step


class _BenchLLM:
    """Deterministic stub — measures execution throughput, not model latency."""

    def context_window(self, cell_id: str = "", agent_id: str = "") -> int:
        return 8192

    def generate(self, prompt: str = "", system: str = "", **kwargs) -> dict:
        return {"content": "bench response", "tool_calls": []}

    def tool_use(self, prompt: str = "", system: str = "", tools=None, **kwargs) -> dict:
        return {
            "content": "bench done",
            "tool_call_results": [],
            "turns": 1,
            "finish_reason": "stop",
            "context_trail": [],
            "tools_elapsed": 0.001,
        }


@pytest.fixture(autouse=True)
def _llm_stub():
    from l1.kernel.ports import _PORTS

    saved = _PORTS.pop("llm", None)
    _PORTS["llm"] = _BenchLLM()
    yield
    if saved is not None:
        _PORTS["llm"] = saved
    else:
        _PORTS.pop("llm", None)


class TestParallelAllCard:
    """PARALLEL_ALL: steps fan out across agents and aggregate results."""

    def test_all_agents_execute(self):
        from l3.agent_terminal import get_terminal, reset_terminals
        from l3.cell import get_cell, reset_cells

        cell = get_cell("parall", ["."])
        for name, role in (("a", "http"), ("b", "business"), ("c", "security")):
            cell.add_agent(name, role=role, territory=["."], auto_boot=True)

        deadline = time.time() + 3.0
        for name in ("a", "b", "c"):
            while time.time() < deadline:
                try:
                    t = get_terminal(name)
                    if t and t.status and t.status.name == "IDLE":
                        break
                except Exception:
                    pass
                time.sleep(0.05)

        card = Card(
            intent="parallel all execution",
            domain=".",
            mode=CardMode.PARALLEL_ALL,
            phases=[
                Phase(
                    name="execute",
                    mode=PhaseMode.PARALLEL,
                    steps=[
                        Step(action="think", target="propose", agent="http"),
                        Step(action="think", target="propose", agent="business"),
                        Step(action="think", target="review", agent="security"),
                    ],
                )
            ],
        )
        try:
            r = cell.execute_card(card, agent_map={"http": "a", "business": "b", "security": "c"})
            steps = r.get("steps", [])
            assert len(steps) == 3, f"expected 3 steps, got {len(steps)}"
            assert all(s.get("success") for s in steps), [s for s in steps if not s.get("success")]
            agents = {s.get("agent_id") for s in steps}
            assert {"a", "b", "c"} <= agents, f"missing agents: {agents}"
        finally:
            reset_terminals()
            reset_cells()
