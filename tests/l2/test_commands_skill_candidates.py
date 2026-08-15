"""L2 command coverage for the R4 skill candidate lifecycle."""

from __future__ import annotations


def test_skills_candidates_list_exposes_candidate_status(monkeypatch, tmp_path):
    """The L2 skill command exposes the same candidate ledger as the API."""
    import l3.memory.r4_candidate_store as candidates
    from l1.kernel.ports import register_port, reset_ports
    from l2.l2_shell.commands.system import _cmd_skills
    from l3.memory.r4_candidate_store import CandidateStore, R4CandidateAdapter

    store = CandidateStore(str(tmp_path / "candidates.json"))
    store.submit_records([{"entry_id": "one", "entry_type": "note", "content": "first"}])
    monkeypatch.setattr(candidates, "_store", store)
    reset_ports()
    register_port("r4_candidates", R4CandidateAdapter(store))

    try:
        result = _cmd_skills(["candidates", "list"])
    finally:
        reset_ports()

    assert result["success"] is True
    assert result["count"] == 1
    assert result["candidates"][0]["state"] == "observed"


def test_skills_candidates_policy_updates_the_port_and_settings(monkeypatch, tmp_path):
    """L2 policy control changes the port implementation and deployment state."""
    from l1.kernel.ports import register_port, reset_ports
    from l2.l2_shell.commands.system import _cmd_skills
    from l3.config.settings_center import get_center
    from l3.memory.r4_candidate_store import CandidateStore, R4CandidateAdapter

    store = CandidateStore(str(tmp_path / "candidates.json"))
    reset_ports()
    register_port("r4_candidates", R4CandidateAdapter(store))
    try:
        result = _cmd_skills(["candidates", "policy", "off", "--role", "l3"])
    finally:
        reset_ports()

    assert result["enabled"] is False
    assert get_center().get("skill.candidate_enabled") is False
