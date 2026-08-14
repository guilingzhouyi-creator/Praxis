"""Identity-with-card wiring tests — card-driven identity injection chain.

Covers the three wiring points that make identity flow with the card:

  1. ``handle_think`` assigns ``_task_intent``/``_task_domain``/``_card_domain``
     on the AgentLoop (revives the ``match_identity`` + ``resolve_domain_fragment``
     prompt channels in ``agent_loop_context``);
  2. decomposed slices carry ``_card_domain`` into per-slice TerminalCard params;
  3. the fine-grained memory gate receives the driving intent/domain so the
     identity-hit follows task dispatch instead of the static binding fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _isolate_identity(tmp_path, monkeypatch):
    """Isolate the identity-binding persistence file per test."""
    monkeypatch.setenv("PRAXIS_IDENTITY_STATE", str(tmp_path / "id_wiring.json"))
    from l1.kernel.identity_binding import reset_identity_binding_manager

    reset_identity_binding_manager()
    yield


class TestLoopIdentityChannels:
    """AgentLoop identity channels fire only when card fields are assigned."""

    def test_card_domain_injects_domain_expert_fragment(self, monkeypatch):
        from l1.kernel.identity_binding import get_identity_binding_manager

        mgr = get_identity_binding_manager()
        r = mgr.bind("cell-1", "tester", "DOMAIN-EXPERT-FRAGMENT", domain_tags=["test"], internal=True)
        assert r.get("success") is True

        import l3.agent.agent_loop_context as alc
        from l3.agent.agent_loop import AgentLoop

        monkeypatch.setattr(alc, "_inject_enabled", lambda domain: domain == "identity")
        loop = AgentLoop(task="run the test suite", agent_id="agent-a", cell_id="cell-1")
        loop._task_intent = "run the test suite"
        loop._task_domain = "test"
        loop._card_domain = "test"
        system, _, _, _ = loop._build_run_context(max_steps=1, model_config=None, engine=None)
        assert "DOMAIN-EXPERT-FRAGMENT" in system

    def test_task_intent_injects_generic_identity_fragment(self, monkeypatch):
        import l3.agent.agent_loop_context as alc
        from l1.kernel.prompts import get_prompt as real_prompt
        from l3.agent.agent_loop import AgentLoop

        def fake_prompt(key, default=""):
            if key == "identity.test.fragment":
                return "GENERIC-TESTER-FRAGMENT"
            return real_prompt(key, default)

        monkeypatch.setattr(alc, "get_prompt", fake_prompt)
        monkeypatch.setattr(alc, "_inject_enabled", lambda domain: domain == "identity")
        loop = AgentLoop(task="verify the auth flow", agent_id="agent-a", cell_id="cell-1")
        loop._task_intent = "verify the coverage of the auth tests"
        loop._task_domain = "test"
        loop._card_domain = "test"
        system, _, _, _ = loop._build_run_context(max_steps=1, model_config=None, engine=None)
        assert "GENERIC-TESTER-FRAGMENT" in system

    def test_unwired_loop_stays_dormant(self, monkeypatch):
        from l1.kernel.identity_binding import get_identity_binding_manager

        mgr = get_identity_binding_manager()
        mgr.bind("cell-1", "tester", "DOMAIN-EXPERT-FRAGMENT", domain_tags=["test"], internal=True)

        import l3.agent.agent_loop_context as alc
        from l3.agent.agent_loop import AgentLoop

        monkeypatch.setattr(alc, "_inject_enabled", lambda domain: domain == "identity")
        loop = AgentLoop(task="run the test suite", agent_id="agent-a", cell_id="cell-1")
        system, _, _, _ = loop._build_run_context(max_steps=1, model_config=None, engine=None)
        assert "DOMAIN-EXPERT-FRAGMENT" not in system


class TestHandleThinkWiring:
    """handle_think assigns card-derived identity fields onto the loop."""

    def test_identity_fields_wired_from_card_params(self, monkeypatch):
        import l3.agent._term_handlers as th
        from l3.agent_terminal import CardMode, TerminalCard

        created = {}

        class RecordingLoop:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                created["loop"] = self

            def add_tool(self, *args, **kwargs):
                pass

            def set_pmu(self, pmu):
                self._pmu = pmu

            def set_card_tags(self, tags):
                self._card_tags = tags

            def run(self, **kwargs):
                return {"success": True, "answer": "ok", "steps": [], "tool_call_results": []}

        monkeypatch.setattr("l3.agent.agent_loop.AgentLoop", RecordingLoop)
        monkeypatch.setattr(th, "_inject_enabled", lambda domain: False)
        monkeypatch.setattr(
            "l3.memory.memory.get_memory",
            lambda: SimpleNamespace(build_context=lambda *a, **k: "", remember=lambda **k: None),
        )
        term = SimpleNamespace(
            agent_id="agent-a",
            role="tester",
            territory=["tests"],
            ring=1,
            cell_id="cell-1",
            context=SimpleNamespace(recent=lambda n: [], store=lambda **k: None),
            model_config=None,
            stdin=[],
            file_cache=SimpleNamespace(invalidate=lambda p: None),
        )
        card = TerminalCard(
            card_id="c1",
            mode=CardMode.EXECUTE,
            action="think",
            target="t1",
            params={"prompt": "verify the login flow", "_card_nature": "review", "_card_domain": "test"},
        )
        out, findings, ok = th.handle_think(term, card, [])
        loop = created["loop"]
        assert ok is True
        assert loop._task_intent == "verify the login flow"
        assert loop._card_domain == "test"
        assert loop._task_domain == "test"
        assert loop._card_nature == "review"


class TestDecomposedSliceDomain:
    """Decomposed slices carry the structured domain into per-slice dispatch."""

    def test_slice_terminal_card_carries_domain(self, monkeypatch):
        import l3.agent_terminal as at
        import l3.cell.components.cell_execute as ce
        from l3.card.models import Card, Phase, PhaseMode, Step

        dispatched = {}

        class FakeTerm:
            def dispatch(self, card):
                dispatched["card"] = card
                return "sub-1"

            def wait_for_result(self, card_id, timeout):
                return _OkResult(True)

        monkeypatch.setattr(at, "get_terminal", lambda *a, **k: FakeTerm())
        sub = Card(
            id="c1-test",
            intent="verify auth",
            domain="tests",
            phases=[Phase(name="p", mode=PhaseMode.PARALLEL, steps=[Step(action="think", target="x")])],
        )
        cell = SimpleNamespace(
            cell_id="cell-1",
            _subagent_pool=None,
            _pmu=SimpleNamespace(increment=lambda *a, **k: None),
        )
        slices = [
            {
                "card": sub,
                "agent_id": "cell-1-tester",
                "role": "tester",
                "territory": ["tests"],
                "agent_map": {"tester": "cell-1-tester"},
            }
        ]
        res = ce._execute_decomposed(cell, slices)
        assert res["success"] is True
        assert dispatched["card"].params["_card_domain"] == "tests"


@dataclass
class _OkResult:
    """Minimal dataclass stand-in for a terminal CardResult."""

    success: bool = True


class TestMemoryIdentityHit:
    """The fine-grained memory gate receives the driving identity-hit."""

    def test_re_inject_filtered_forwards_identity_hit(self, monkeypatch):
        import l3.memory.memory_supply_chain as msc

        seen = {}

        class FakeFilter:
            def filter_entries(self, entries, **kwargs):
                seen.update(kwargs)
                return entries

        monkeypatch.setattr("l3.memory.memory_domain_filter.get_memory_filter", lambda: FakeFilter())
        out = msc.re_inject_filtered([{"id": "e1"}], cell_id="c1", intent="write a unit test", domain="test")
        assert out == [{"id": "e1"}]
        assert seen["cell_id"] == "c1"
        assert seen["intent"] == "write a unit test"
        assert seen["domain"] == "test"

    def test_recall_forwards_identity_hit(self, monkeypatch):
        import l3.memory.memory_query as mq
        from l3.memory.memory_ring import MemEntry

        class FakeFilter:
            def status(self):
                return {"enabled": True}

        class FakeRing:
            def query(self, agent_id, entry_type, tag, limit):
                return [MemEntry(id="e1", agent_id="a", entry_type="note", content="x", tags=["test"])]

        class QueryHost(mq.MemoryQueryMixin):
            pass

        q = QueryHost()
        q._ring = lambda r: FakeRing()
        q.short = q.working = q.stats = None

        seen = {}

        def fake_reinject(entries, **kwargs):
            seen.update(kwargs)
            return entries

        monkeypatch.setattr("l3.memory.memory_domain_filter.get_memory_filter", lambda: FakeFilter())
        monkeypatch.setattr("l3.memory.memory_supply_chain.re_inject_filtered", fake_reinject)
        res = q.recall(intent="write a unit test", domain="test", rings=[1])
        assert [e.id for e in res] == ["e1"]
        assert seen["intent"] == "write a unit test"
        assert seen["domain"] == "test"

    def test_memory_context_gate_filters_knowledge_block(self, monkeypatch):
        import l3.memory.memory_context as mc
        from l3.memory.memory_ring import MemEntry

        class FakeFilter:
            def status(self):
                return {"enabled": True}

            def is_allowed(self, entry, **kwargs):
                return "test" in (entry.get("tags") or [])

        monkeypatch.setattr("l3.memory.memory_domain_filter.get_memory_filter", lambda: FakeFilter())

        class Ring:
            def __init__(self, entries):
                self._entries = entries

            def query(self, **kwargs):
                return self._entries

            def summarize(self, agent_id):
                return ""

        mem = SimpleNamespace(
            working=Ring([]),
            short=Ring([]),
            long=Ring(
                [
                    MemEntry(id="e1", agent_id="a", entry_type="note", content="KEEP-ME", tags=["test"]),
                    MemEntry(id="e2", agent_id="a", entry_type="note", content="DROP-ME", tags=["build"]),
                ]
            ),
        )
        out = mc.build_context(mem, "agent-a", intent="run the unit tests", domain="test")
        assert "KEEP-ME" in out
        assert "DROP-ME" not in out

    def test_memory_context_gate_disabled_passes_all(self, monkeypatch):
        import l3.memory.memory_context as mc
        from l3.memory.memory_ring import MemEntry

        class FakeFilter:
            def status(self):
                return {"enabled": False}

        monkeypatch.setattr("l3.memory.memory_domain_filter.get_memory_filter", lambda: FakeFilter())

        class Ring:
            def query(self, **kwargs):
                return [MemEntry(id="e1", agent_id="a", entry_type="note", content="A", tags=["test"])]

            def summarize(self, agent_id):
                return ""

        mem = SimpleNamespace(working=Ring(), short=Ring(), long=Ring())
        out = mc.build_context(mem, "agent-a", intent="run the unit tests", domain="test")
        assert "A" in out

    def test_memory_inject_threads_identity_hit(self, monkeypatch):
        import l3.memory.memory_inject as mi

        seen = {}

        class FakeMemory:
            def build_context(self, agent_id, max_tokens=1024, intent="", domain=""):
                seen.update(intent=intent, domain=domain)
                return "ctx"

        monkeypatch.setattr("l3.memory.memory.get_memory", lambda: FakeMemory())
        out = mi.build_context("agent-a", prompt="write a unit test", intent="write a unit test", domain="test")
        assert out == "ctx"
        assert seen["intent"] == "write a unit test"
        assert seen["domain"] == "test"
