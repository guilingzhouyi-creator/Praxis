"""api_handler — fail-closed auth default (W2.1)."""

from __future__ import annotations


def test_auth_denied_without_token(monkeypatch) -> None:
    """No static token and no AuthPort must deny by default (fail-closed)."""
    monkeypatch.delenv("PRAXIS_AUTH_OPEN", raising=False)
    from l4.api.api_handler import _auth_ok

    assert _auth_ok({}, "") is False


def test_auth_open_env_optout(monkeypatch) -> None:
    """PRAXIS_AUTH_OPEN=1 explicitly opts back into the open default."""
    monkeypatch.setenv("PRAXIS_AUTH_OPEN", "1")
    from l4.api.api_handler import _auth_ok

    assert _auth_ok({}, "") is True


def test_auth_static_token_still_works() -> None:
    """The static shared token continues to authenticate requests."""
    from l4.api.api_handler import _auth_ok

    assert _auth_ok({"X-API-Token": "sekret"}, "sekret") is True
    assert _auth_ok({"X-API-Token": "wrong"}, "sekret") is False
