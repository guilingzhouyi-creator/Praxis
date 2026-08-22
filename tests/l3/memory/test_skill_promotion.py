"""P1.3/P1.4 slice tests — promotion transaction + canary automation."""

from __future__ import annotations

from l3.memory.skill_promotion import evaluate_canary, promote_skill_transaction, quarantine_skill


class _FakeSM:
    """SkillManager double recording mutations; can simulate failures."""

    def __init__(self, existing: dict | None = None, fail_register: bool = False):
        self.skills = dict(existing or {})
        self.fail_register = fail_register
        self.events: list[tuple] = []

    def get(self, name):
        return self.skills.get(name)

    def register(self, name, data, internal=True):
        if self.fail_register:
            return {"success": False, "error": "injected register failure"}
        self.skills[name] = dict(data)
        self.events.append(("register", name))
        return {"success": True, "name": name}

    def update(self, name, patch, internal=True):
        if name not in self.skills:
            return {"success": False, "error": "unknown"}
        self.skills[name].update(patch)
        self.events.append(("update", name))
        return {"success": True}

    def delete(self, name, internal=True):
        self.skills.pop(name, None)
        self.events.append(("delete", name))
        return {"success": True}


class _FakeStore:
    """CandidateStore double with a promoted-state ledger + failure switch."""

    def __init__(self, validated=(), fail_transition=False):
        self.validated = set(validated)
        self.promoted: dict[str, str] = {}
        self.fail_transition = fail_transition

    def transition(self, candidate_id, state, skill_name=""):
        if candidate_id not in self.validated:
            return {"success": False, "error": f"candidate not found: {candidate_id}"}
        if state != "promoted" and state != "retired":
            return {"success": False, "error": f"invalid target state: {state}"}
        if self.fail_transition:
            return {"success": False, "error": "injected ledger failure"}
        self.promoted[candidate_id] = skill_name
        return {"success": True, "state": state, "skill_name": skill_name}


def test_promotion_happy_path(tmp_path):
    jp = tmp_path / "promo.json"
    sm = _FakeSM()
    store = _FakeStore(validated={"c-1"})
    r = promote_skill_transaction("c-1", {"name": "skill-a", "prompt": "p"}, sm=sm, store=store, journal_path=str(jp))
    assert r["success"] is True
    assert "skill-a" in sm.skills
    assert store.promoted["c-1"] == "skill-a"


def test_promotion_idempotent_on_replay(tmp_path):
    jp = tmp_path / "promo.json"
    sm = _FakeSM()
    store = _FakeStore(validated={"c-2"})
    kw = dict(sm=sm, store=store, journal_path=str(jp))
    r1 = promote_skill_transaction("c-2", {"name": "skill-b", "prompt": "p"}, **kw)
    events_after_first = len(sm.events)
    r2 = promote_skill_transaction("c-2", {"name": "skill-b", "prompt": "p"}, **kw)
    assert r1["success"] and r2["success"]
    assert r2.get("idempotent") is True
    assert len(sm.events) == events_after_first  # no duplicate library writes


def test_ledger_failure_compensates_library(tmp_path):
    """Register ok but ledger fails → the fresh skill is rolled back."""
    jp = tmp_path / "promo.json"
    sm = _FakeSM()
    store = _FakeStore(validated={"c-3"}, fail_transition=True)
    r = promote_skill_transaction("c-3", {"name": "skill-c", "prompt": "p"}, sm=sm, store=store, journal_path=str(jp))
    assert r["success"] is False
    assert r.get("compensated") is True
    assert "skill-c" not in sm.skills


def test_register_failure_leaves_no_side_effects(tmp_path):
    jp = tmp_path / "promo.json"
    sm = _FakeSM(fail_register=True)
    store = _FakeStore(validated={"c-4"})
    r = promote_skill_transaction("c-4", {"name": "skill-d"}, sm=sm, store=store, journal_path=str(jp))
    assert r["success"] is False
    assert store.promoted == {}


def test_canary_evaluator_thresholds():
    below_trials = evaluate_canary({"injected": 2, "useful": 0})
    assert below_trials["pass"] is True and below_trials["trials_met"] is False

    failing_rate = evaluate_canary({"injected": 10, "useful": 5})
    assert failing_rate["pass"] is False
    assert any(r.startswith("success_rate") for r in failing_rate["reasons"])

    passing = evaluate_canary({"injected": 10, "useful": 9})
    assert passing["pass"] is True

    latency = evaluate_canary({"injected": 10, "useful": 9, "avg_latency_ms": 500}, max_latency_ms=200)
    assert latency["pass"] is False
    assert any(r.startswith("latency_ms") for r in latency["reasons"])


def test_quarantine_tags_and_deprecates(tmp_path):
    class SM:
        skills = {
            "s1": {"status": "active", "tags": ["evolved"], "prompt": "p"},
        }

        def get(self, n):
            return self.skills.get(n)

        def update(self, n, patch, internal=True):
            self.skills[n].update(patch)
            return {"success": True}

    archived = []
    sm = SM()
    r = quarantine_skill("s1", ["success_rate:0.40<0.80"], sm=sm, archive_cb=lambda n, rec: archived.append(n))
    assert r["success"] is True
    assert sm.skills["s1"]["status"] == "deprecated"
    assert "canary-quarantined" in sm.skills["s1"]["tags"]
    assert archived == ["s1"]
