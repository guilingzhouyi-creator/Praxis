"""Tests for LLM provider failover (model-failover)."""

from __future__ import annotations

from l1.kernel.params.api import LLM_FAILOVER_THRESHOLD
from l4.llm.llm_retry import reset_failover_state


class _FakeProvider:
    """Minimal provider stub with get_headers/get_api_url."""

    name = "openai"
    model = "gpt-4o"

    def __init__(self, url: str = "http://localhost:1/v1/chat/completions"):
        self._url = url

    def get_headers(self) -> dict:
        return {}

    def get_api_url(self, url: str) -> str:
        return self._url


def _make_engine():
    """Build an engine with a failing primary provider and a fallback."""
    from l4.llm.llm_engine import LLMEngine

    engine = LLMEngine()
    engine.config = engine.config.__class__(
        provider="openai",
        model="gpt-4o",
        api_url="http://primary.invalid/v1/chat/completions",
        api_key="k1",
    )
    engine._provider = _FakeProvider("http://primary.invalid/v1/chat/completions")
    return engine


def _failover_fallback_factory():
    """Return a get_fallback bound-style stub over the real registry class."""

    def _get_fallback(self, provider: str, model: str = ""):
        if provider == "openai":
            return {
                "provider": "deepseek",
                "model": "deepseek-v4",
                "api_url": "http://fallback.invalid/v1",
                "api_key": "k2",
            }
        if provider == "deepseek":
            return {
                "provider": "anthropic",
                "model": "claude",
                "api_url": "http://anthropic.invalid/v1",
                "api_key": "k3",
            }
        return None

    return _get_fallback


def test_failover_not_triggered_below_threshold(monkeypatch):
    """Consecutive failures below the threshold do NOT switch providers."""
    reset_failover_state()
    engine = _make_engine()

    def _fail_post(url, body, headers, timeout):
        return 500, b"server error", {}

    monkeypatch.setattr("l4.llm.http_pool.http_post", _fail_post)
    monkeypatch.setattr("l4.llm.llm_retry.http_post", _fail_post)

    for _ in range(LLM_FAILOVER_THRESHOLD - 1):
        engine._call_api(b"{}")
    assert engine.config.provider == "openai", "provider must not switch below threshold"


def test_failover_switches_after_threshold(monkeypatch):
    """At the threshold, the provider switches to the fallback and replays."""
    reset_failover_state()
    engine = _make_engine()
    calls = {"n": 0}

    def _fail_post(url, body, headers, timeout):
        calls["n"] += 1
        # Fallback endpoint succeeds.
        if "fallback" in url:
            return 200, b'{"choices":[{"message":{"content":"ok"}}],"usage":{}}', {}
        return 500, b"server error", {}

    monkeypatch.setattr("l4.llm.http_pool.http_post", _fail_post)
    monkeypatch.setattr("l4.llm.llm_retry.http_post", _fail_post)
    monkeypatch.setattr(
        "l1.kernel.model_registry.ModelRegistry.get_fallback",
        _failover_fallback_factory(),
    )

    for _ in range(LLM_FAILOVER_THRESHOLD):
        engine._call_api(b"{}")
    # After the threshold failure, the replayed call hit the fallback.
    assert engine.config.provider == "deepseek", f"expected switch to deepseek, got {engine.config.provider}"
    assert engine.config.api_key == "k2"
    assert calls["n"] >= LLM_FAILOVER_THRESHOLD


def test_failover_cooldown_prevents_thrash(monkeypatch):
    """After a switch, failures within the cooldown do not re-trigger a switch."""
    reset_failover_state()
    engine = _make_engine()

    def _fail_post(url, body, headers, timeout):
        return 500, b"server error", {}

    monkeypatch.setattr("l4.llm.http_pool.http_post", _fail_post)
    monkeypatch.setattr("l4.llm.llm_retry.http_post", _fail_post)
    monkeypatch.setattr(
        "l1.kernel.model_registry.ModelRegistry.get_fallback",
        _failover_fallback_factory(),
    )

    for _ in range(LLM_FAILOVER_THRESHOLD * 3):
        engine._call_api(b"{}")
    # Cooldown: only ONE switch should have happened (openai -> deepseek).
    assert engine.config.provider == "deepseek", f"expected cooldown to hold at deepseek, got {engine.config.provider}"


def test_failover_success_resets_counter(monkeypatch):
    """A successful call resets the consecutive-failure counter."""
    reset_failover_state()
    engine = _make_engine()
    calls = {"n": 0}

    def _flaky_post(url, body, headers, timeout):
        calls["n"] += 1
        if calls["n"] <= LLM_FAILOVER_THRESHOLD - 1:
            return 500, b"server error", {}
        return 200, b'{"choices":[{"message":{"content":"ok"}}],"usage":{}}', {}

    monkeypatch.setattr("l4.llm.http_pool.http_post", _flaky_post)
    monkeypatch.setattr("l4.llm.llm_retry.http_post", _flaky_post)

    out = {}
    for _ in range(LLM_FAILOVER_THRESHOLD):
        out = engine._call_api(b"{}")
        if out.get("content"):
            break
    assert out.get("content") == "ok"
    assert engine.config.provider == "openai", "success must not switch provider"


def test_failover_no_fallback_keeps_provider(monkeypatch):
    """No registry fallback available: the provider is kept, error returned."""
    reset_failover_state()
    engine = _make_engine()

    def _fail_post(url, body, headers, timeout):
        return 500, b"server error", {}

    monkeypatch.setattr("l4.llm.http_pool.http_post", _fail_post)
    monkeypatch.setattr("l4.llm.llm_retry.http_post", _fail_post)

    def _no_fallback(self, provider, model=""):
        return None

    monkeypatch.setattr("l1.kernel.model_registry.ModelRegistry.get_fallback", _no_fallback)

    for _ in range(LLM_FAILOVER_THRESHOLD):
        out = engine._call_api(b"{}")
    assert engine.config.provider == "openai"
    assert out.get("error")
