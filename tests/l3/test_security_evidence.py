"""Security evidence chain tests — attack-posture bypass audit (deterministic).

Covers: chain orchestration (open / follow-open / close), fixity hashing and
tamper detection, verdict derivation (clean / warranted / bypassed), the
metric-sink bridge, findings anchoring, query/search/report, and an
end-to-end posture-switch scenario through the real modules (security_mode,
skill manager, use_skill). No LLM — fully deterministic, mirror/attack
matrix style.
"""

from __future__ import annotations

import json

import pytest

from l3.tool_system.security_evidence import (
    DECISION_ALLOW,
    DECISION_BLOCK,
    DECISION_BYPASS,
    DECISION_CHANGE,
    DECISION_FULL_POWER,
    DECISION_WARN,
    VERDICT_BYPASSED,
    VERDICT_CLEAN,
    VERDICT_WARRANTED,
    SecurityEvidence,
    get_evidence,
    record_evidence,
    record_from_metric,
    reset_evidence,
)


def _fresh(tmp_path, name: str = "ev.jsonl") -> SecurityEvidence:
    """Fresh collector instance writing into a tmp file (no env dependence)."""
    return SecurityEvidence(path=str(tmp_path / name))


# ── chain orchestration + fixity ──


class TestChainOrchestration:
    def test_begin_chain_reuses_open_kind(self, tmp_path):
        ev = _fresh(tmp_path)
        cid1 = ev.begin_chain("attack", source="test")
        cid2 = ev.begin_chain("attack", source="test")
        assert cid1 == cid2

    def test_record_follows_open_posture_chain(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        landed = ev.record(phase="use_skill", gate="g", decision=DECISION_BLOCK, target="s1")
        assert landed == cid
        assert ev.chain_evidence(cid)[0]["target"] == "s1"

    def test_record_now_chain_opens_ambient(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.record(phase="g4", decision=DECISION_BLOCK, target="t1")
        cid2 = ev.record(phase="g4", decision=DECISION_WARN, target="t2")
        assert cid == cid2
        assert cid != ""

    def test_close_open_ends_attack_chain(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        assert ev.chains()[0]["open"] is True
        ev.close_open(kind="attack")
        assert ev.chains()[0]["open"] is False
        assert ev.record(phase="g4", decision=DECISION_BLOCK, target="t") != cid

    def test_close_chain_idempotent(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("downgrade", source="shell")
        assert ev.close_chain(cid)["success"]
        r = ev.close_chain(cid)
        assert r["success"] and r["closed"] is not None
        assert ev.close_chain("nope")["success"] is False


class TestFixity:
    def test_hash_recorded_and_persisted(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        ev.record("harness", "harness_mode", DECISION_CHANGE, "minimal", "api", chain_kind="attack")
        ev.record("g4", "g4", DECISION_BLOCK, "nuke", "sink", chain_kind="attack")
        fix = ev.verify_chain(cid)
        assert fix["checked"] == 2 and fix["ok"] is True and fix["bad"] == 0
        rows = ev.query_evidence(chain_id=cid)
        assert rows[0]["hash_prefix"] and len(rows[0]["raw_hash"]) == 64

    def test_tamper_detected(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        ev.record("g4", "g4", DECISION_BLOCK, "tool-x", "sink", chain_kind="attack")
        path = ev._path
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        rows[-1]["target"] = "evil-target"  # tamper with the persisted row
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        fix = ev.verify_chain(cid)
        assert fix["ok"] is False and fix["bad"] >= 1

    def test_reload_restores_window(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        ev.record("g4", "g4", DECISION_BLOCK, "nuke", "sink", chain_kind="attack")
        ev2 = SecurityEvidence(path=ev._path)  # fresh instance, same file
        assert len(ev2.chain_evidence(cid)) == 1
        assert ev2.query_evidence(skill="nuke")  # single stale match


# ── verdict derivation / analysis ──


class TestVerdicts:
    def test_clean_chain(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("ambient", source="")
        ev.record("g4", "g4", DECISION_BLOCK, "nuke", "sink")
        a = ev.analyze(cid)
        assert a["verdict"] == VERDICT_CLEAN
        assert {f["kind"] for f in a["findings"]} == {"block"}

    def test_bypassed_verdict(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("policy-bypass", source="policy")
        ev.record(
            "use_skill",
            "posture_use",
            DECISION_BYPASS,
            "rev-helper",
            "use_skill",
            tags={"soft_bypass": "1"},
        )
        a = ev.analyze(cid)
        assert a["verdict"] == VERDICT_BYPASSED
        assert any(f["kind"] == "bypass" and f["severity"] == "risk" for f in a["findings"])

    def test_warranted_via_escalation(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        ev.record("g4", "g4", DECISION_FULL_POWER, "nuke", "sink")
        a = ev.analyze(cid)
        assert a["verdict"] == VERDICT_WARRANTED
        assert any(f["kind"] == "escalation" for f in a["findings"])

    def test_warranted_via_offense_allow(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        ev.record("use_skill", "posture_use", DECISION_ALLOW, "rev-helper", "use_skill", tags={"nature": "offensive"})
        a = ev.analyze(cid)
        assert a["verdict"] == VERDICT_WARRANTED
        assert any(f["kind"] == "offense_use" for f in a["findings"])

    def test_findings_anchor_real_evidence(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        ev.record("g4", "g4", DECISION_FULL_POWER, "nuke", "sink")
        ev.record("injection", "posture_injection", DECISION_BLOCK, "other", "loop")
        a = ev.analyze(cid)
        ids = {e["evidence_id"] for e in ev.chain_evidence(cid)}
        assert all(f["evidence_id"] in ids for f in a["findings"])
        assert a["decisions"].get(DECISION_FULL_POWER) == 1


# ── metric bridge / query / search / report ──


class TestMetricBridge:
    def test_g4_metrics_translate(self, tmp_path):
        ev = _fresh(tmp_path)
        ev.begin_chain("attack", source="")
        ev.record_from_metric("security.gate.g4.full_power", 1.0, {"tool": "nuke"})
        ev.record_from_metric("security.gate.g4.auto_approved", 1.0, {"tool": "wipe"})
        ev.record_from_metric("security.gate.g4.blocked", 1.0, {"tool": "deny"})
        ev.record_from_metric("security.gate.unknown.metric", 1.0, {})
        rows = {e["target"]: e["decision"] for e in ev.query_evidence()}
        assert rows["nuke"] == DECISION_FULL_POWER
        assert rows["wipe"] == "AUTO_APPROVED"
        assert rows["deny"] == DECISION_BLOCK
        assert len(ev.query_evidence()) == 3

    def test_metric_bridge_unknown_ignored(self, tmp_path):
        ev = _fresh(tmp_path)
        assert ev.record_from_metric("security.gate.unknown", 1.0, {}) == ""


class TestQuerySearchReport:
    def test_query_filters(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("attack", source="api")
        ev.record("g4", "g4", DECISION_BLOCK, "tool-a", "api")
        ev.record("injection", "posture_injection", DECISION_ALLOW, "rev-a", "loop")
        assert len(ev.query_evidence(chain_id=cid)) == 2
        assert len(ev.query_evidence(skill="rev-a")) == 1
        assert len(ev.query_evidence(decision=DECISION_BLOCK)) == 1
        assert len(ev.query_evidence(decision="nope")) == 0
        assert len(ev.query_evidence(limit=1)) == 1

    def test_search_hits_target_and_tags(self, tmp_path):
        ev = _fresh(tmp_path)
        ev.begin_chain("attack", source="")
        ev.record("injection", "posture_injection", DECISION_BLOCK, "rev-shell", "loop", tags={"nature": "offensive"})
        assert len(ev.search("rev-shell")) == 1
        assert len(ev.search("offensive")) == 1
        assert len(ev.search("zzz")) == 0

    def test_report_markdown(self, tmp_path):
        ev = _fresh(tmp_path)
        cid = ev.begin_chain("downgrade", source="shell")
        ev.record("harness", "harness_mode", DECISION_CHANGE, "minimal", "shell")
        r = ev.report(cid)
        assert r["success"]
        assert r["verdict"] in (VERDICT_CLEAN, VERDICT_WARRANTED, VERDICT_BYPASSED)
        for token in ("# Evidence Chain", "## Timeline", "## Findings", "## Fixity", "minimal"):
            assert token in r["markdown"]
        assert r["fixity"]["ok"] is True

    def test_chains_newest_first(self, tmp_path):
        ev = _fresh(tmp_path)
        ev.begin_chain("attack", source="api")
        ev.begin_chain("policy-bypass", source="policy")
        rows = ev.chains()
        assert rows[0]["kind"] == "policy-bypass"
        assert rows[1]["kind"] == "attack"

    def test_module_level_best_effort(self, tmp_path, monkeypatch):
        from l3.tool_system import security_evidence as mod

        monkeypatch.setattr(mod, "get_evidence", lambda: _fresh(tmp_path, "isolated.jsonl"))
        cid = record_evidence("g4", "g4", DECISION_BLOCK, "t", "api")
        assert cid.startswith(mod.EVIDENCE_CHAIN_ID_PREFIX)
        assert record_from_metric("security.gate.g4.blocked", 1.0, {"tool": "x"}) is None  # bridge never raises


# ── end-to-end posture-switch scenario (real modules, no mocks) ──


@pytest.fixture
def _evidence_env(tmp_path, monkeypatch):
    """Isolated evidence path + fresh singleton for the integration scenario."""
    monkeypatch.setenv("PRAXIS_SECURITY_EVIDENCE_PATH", str(tmp_path / "scenario.jsonl"))
    reset_evidence()
    yield get_evidence()
    reset_evidence()


def _attack_chain(env) -> str:
    """Return the newest open/closed attack chain id."""
    return [c for c in env.chains() if c["kind"] == "attack"][0]["chain_id"]


class TestPostureScenario:
    def test_attack_switch_lifecycle(self, _evidence_env):
        from l3.tool_system.security_mode import set_security_mode

        r = set_security_mode("security-test", confirmed=True, source="scenario")
        assert r["success"]
        assert r["posture"].get("full_power") is True
        chains = [c for c in _evidence_env.chains() if c["kind"] == "attack"]
        assert len(chains) == 1 and chains[0]["open"] is True

        r2 = set_security_mode("productive", source="scenario")
        assert r2["success"]
        chains = [c for c in _evidence_env.chains() if c["kind"] == "attack"]
        assert chains[0]["open"] is False
        # restore evidence landed on the same attack chain, then closed it
        restore = _evidence_env.query_evidence(phase="posture", decision=DECISION_CHANGE)
        assert any("restore" in e["target"] for e in restore)

    def test_denied_confirmation_leaves_warning(self, _evidence_env):
        from l3.tool_system.security_mode import set_security_mode

        r = set_security_mode("security-test", confirmed=False, source="scenario")
        assert not r["success"]
        rows = _evidence_env.query_evidence(decision=DECISION_WARN)
        assert any("security-test" in e["target"] for e in rows)

    def test_offensive_skill_flow_lands_on_attack_chain(self, _evidence_env):
        from l1.kernel.skill import get_skill_manager
        from l3.tool_system.security_mode import set_security_mode
        from l3.tools._skills import use_skill

        sm = get_skill_manager()
        sm.create(name="rev-helper", description="d", prompt="p", posture="offensive", internal=True)
        assert sm.get("rev-helper")["posture"] == "offensive"

        set_security_mode("security-test", confirmed=True, source="scenario")
        attack_cid = _attack_chain(_evidence_env)

        r = use_skill({"name": "rev-helper"}, "agent-x")
        assert not r["success"]
        rows = _evidence_env.query_evidence(chain_id=attack_cid, skill="rev-helper")
        assert rows and rows[-1]["decision"] == DECISION_BLOCK

        r2 = use_skill({"name": "rev-helper", "_card_nature": "offensive"}, "agent-x")
        assert r2["success"]
        rows = _evidence_env.query_evidence(chain_id=attack_cid, skill="rev-helper")
        assert rows[-1]["decision"] == DECISION_ALLOW
        assert _evidence_env.analyze(attack_cid)["verdict"] == VERDICT_WARRANTED

    def test_soft_bypass_leaves_bypassed_verdict(self, _evidence_env):
        from l1.kernel.event import get_bus
        from l1.kernel.skill import get_skill_manager
        from l3.tool_system.security_evidence import ensure_listener
        from l3.tools._skills import use_skill

        ensure_listener(force=True)
        sm = get_skill_manager()
        sm.create(name="rev-soft", description="d", prompt="p", posture="offensive", internal=True)

        sm.set_offensive_policy(enabled=False)

        # The L1 policy write must be observable on the bus (synchronous history).
        assert any(h["type"] == "security_policy_change" for h in get_bus().history())

        r = use_skill({"name": "rev-soft"}, "agent-x")
        assert r["success"]  # gate disabled → granted as a soft bypass

        bypass_rows = _evidence_env.query_evidence(decision=DECISION_BYPASS)
        assert any(e["target"] == "rev-soft" for e in bypass_rows)

        verdicts = [_evidence_env.analyze(c["chain_id"])["verdict"] for c in _evidence_env.chains()]
        assert VERDICT_BYPASSED in verdicts

    def test_metric_sink_reaches_evidence(self, _evidence_env):
        # This is what the boot sink does for L1 decisions (simulated here).
        from l1.kernel.constitution import set_metric_sink
        from l3.tool_system.security_evidence import record_from_metric as _rfm

        set_metric_sink(lambda name, value, tags=None: _rfm(name, value, tags))
        from l1.kernel.constitution import get_constitution

        get_constitution()  # ensure module loaded (statements below still sync)
        record_from_metric("security.gate.g4.blocked", 1.0, {"tool": "pwn-tool"})
        points = _evidence_env.query_evidence(skill="pwn-tool")
        assert points and points[0]["decision"] == DECISION_BLOCK and points[0]["phase"] == "g4"
