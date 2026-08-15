"""Skill candidate API handler tests."""

from __future__ import annotations


def _candidate(monkeypatch, tmp_path):
    import l3.memory.r4_candidate_store as candidates
    from l3.memory.r4_candidate_store import CandidateStore

    store = CandidateStore(str(tmp_path / "candidates.json"))
    submitted = store.submit_records(
        [
            {"entry_id": "one", "entry_type": "note", "cell_id": "cell-build", "content": "first"},
            {"entry_id": "two", "entry_type": "note", "cell_id": "cell-build", "content": "second"},
        ]
    )
    monkeypatch.setattr(candidates, "_store", store)
    return submitted["candidates"][0]


def test_candidate_handlers_list_and_validate(monkeypatch, tmp_path):
    """Candidate API lists evidence and validates via the developer gate."""
    from l4.api_handlers.api_handlers_skills import handle_skill_candidate_validate, handle_skill_candidates_list

    candidate = _candidate(monkeypatch, tmp_path)

    listed = handle_skill_candidates_list({})
    validated = handle_skill_candidate_validate({"role": "l3"}, candidate_id=candidate["id"])

    assert listed["count"] == 1
    assert validated["success"] is True
    assert validated["candidate"]["state"] == "validated"


def test_candidate_policy_handler_requires_developer_role(monkeypatch, tmp_path):
    """Candidate collection policy cannot be changed by an anonymous caller."""
    from l4.api_handlers.api_handlers_skills import handle_skill_candidates_policy_set

    _candidate(monkeypatch, tmp_path)

    denied = handle_skill_candidates_policy_set({"enabled": False})
    allowed = handle_skill_candidates_policy_set({"role": "l3", "enabled": False})

    assert denied["success"] is False
    assert allowed["success"] is True
    assert allowed["policy"]["enabled"] is False


def test_candidate_list_handler_uses_registered_ledger_port():
    """The API control surface uses a swappable ledger implementation."""
    from l1.kernel.ports import register_port, reset_ports
    from l4.api_handlers.api_handlers_skills import handle_skill_candidates_list

    class RustLedger:
        """Language-neutral ledger stub used to prove the API port seam."""

        def list_candidates(self, state=""):
            return [{"id": "rust-1", "state": "observed"}]

        def status(self):
            return {"enabled": True, "counts": {"observed": 1}}

    reset_ports()
    register_port("r4_candidates", RustLedger())
    try:
        result = handle_skill_candidates_list()
    finally:
        reset_ports()

    assert result["count"] == 1
    assert result["candidates"][0]["id"] == "rust-1"


def test_candidate_lifecycle_routes_are_registered():
    """Every candidate lifecycle handler is reachable through the v2 route table."""
    from l4.api.api_routes import API_ROUTES

    registered = {(method, path) for method, path, _, _ in API_ROUTES}
    expected = {
        ("GET", "/api/v2/skills/candidates"),
        ("GET", "/api/v2/skills/candidates/policy"),
        ("POST", "/api/v2/skills/candidates/policy"),
        ("GET", "/api/v2/skills/candidates/{candidate_id}"),
        ("POST", "/api/v2/skills/candidates/{candidate_id}/validate"),
        ("POST", "/api/v2/skills/candidates/{candidate_id}/publish"),
        ("POST", "/api/v2/skills/candidates/{candidate_id}/activate"),
        ("POST", "/api/v2/skills/candidates/{candidate_id}/retire"),
    }

    assert expected <= registered
