"""Tests for stateful/stateless protocol resolution + degradation (P1-2)."""

from __future__ import annotations


class _FakeStrategy:
    """Minimal strategy stub with a configurable protocol value."""

    def __init__(self, protocol: str) -> None:
        """Bind the configured protocol value."""
        self.protocol = protocol

    def optimize(self, prompt: str, system: str, user_id: str = ""):
        """Return the inputs unchanged with no extra cache options."""
        return prompt, system, {}


class _StatelessProvider:
    """Provider without native message-list support (e.g. mock/ollama)."""

    name = "mock"
    model = "mock"

    @property
    def capabilities(self):
        """Advertise only basic generation capabilities."""
        return {"max_tokens", "temperature"}

    def generate(
        self, prompt: str, system: str = "", max_tokens: int = 0, user_id: str = "", cache_retention: str = "", **kw
    ) -> dict:
        """Record the call and return a deterministic completion."""
        return {"content": "ok", "protocol": "stateless"}

    def probe(self) -> dict:
        """Probe without any CACHE_CAP_* capability keys."""
        return {"supports": {"max_tokens"}, "context_window": 0, "model": "mock"}


class _StatefulProvider(_StatelessProvider):
    """Provider that also implements generate_with_messages (e.g. openai)."""

    name = "openai"
    model = "gpt-4o"

    @property
    def capabilities(self):
        """Advertise message-list generation, user_id and prefix caching."""
        return {"max_tokens", "temperature", "generate_with_messages", "user_id", "prefix_cache"}

    def generate_with_messages(self, messages, max_tokens=0, user_id="", cache_retention=0):
        """Native message-list generation path."""
        return {"content": "ok", "protocol": "stateful", "cache_hit_tokens": 10, "cache_miss_tokens": 90}


class _DeviceManager:
    """Device manager stub that always allows calls."""

    def check_rate(self, device_name):
        return {"allowed": True}

    def record_call(self, device_name, success):
        return None


def test_resolve_protocol_pure():
    """The pure decision function is deterministic and fail-closed."""
    from l4.llm.llm_engine import resolve_protocol

    assert resolve_protocol("auto", True) == "stateful"
    assert resolve_protocol("auto", False) == "stateless"
    assert resolve_protocol("stateful", False) == "stateful"
    assert resolve_protocol("stateless", True) == "stateless"
    assert resolve_protocol("bogus", True) == "stateless"
    assert resolve_protocol("", True) == "stateless"


def test_get_protocol_auto_resolves_by_capability():
    """auto prefers stateful only when the provider supports messages."""
    from l4.llm.llm_engine import LLMEngine

    engine = LLMEngine()
    engine.config = engine.config.__class__(provider="openai", model="gpt-4o")
    engine._provider = _StatefulProvider()
    engine._get_strategy = lambda: _FakeStrategy("auto")  # noqa: E731
    assert engine._get_protocol() == "stateful"

    engine._provider = _StatelessProvider()
    assert engine._get_protocol() == "stateless"


def test_get_protocol_config_stateful_degrades_to_stateless():
    """A configured stateful protocol is not downgraded by capability alone."""
    from l4.llm.llm_engine import LLMEngine

    engine = LLMEngine()
    engine.config = engine.config.__class__(provider="mock", model="mock")
    engine._provider = _StatelessProvider()
    engine._get_strategy = lambda: _FakeStrategy("stateful")  # noqa: E731
    assert engine._get_protocol() == "stateful"
    assert engine._provider_supports_stateful() is False


def test_generate_degrades_and_surfaces_reason(monkeypatch):
    """A stateful request against a stateless-only provider falls back + logs."""
    from l4.llm.llm_engine import LLMEngine

    engine = LLMEngine()
    engine.config = engine.config.__class__(provider="mock", model="mock")
    provider = _StatelessProvider()
    engine._provider = provider
    engine._get_strategy = lambda: _FakeStrategy("stateful")  # noqa: E731
    monkeypatch.setattr("l1.kernel.device.get_device_manager", lambda: _DeviceManager())

    result = engine.generate("hello", system="sys")
    assert result["protocol"] == "stateless"
    assert result["protocol_degraded"] is True
    assert "generate_with_messages" in result["protocol_degrade_reason"]


def test_generate_stateful_path_marks_protocol(monkeypatch):
    """A capable provider uses the native message-list path and marks it."""
    from l4.llm.llm_engine import LLMEngine

    engine = LLMEngine()
    engine.config = engine.config.__class__(provider="openai", model="gpt-4o")
    provider = _StatefulProvider()
    engine._provider = provider
    engine._get_strategy = lambda: _FakeStrategy("stateful")  # noqa: E731
    monkeypatch.setattr("l1.kernel.device.get_device_manager", lambda: _DeviceManager())

    result = engine.generate("hello", system="sys")
    assert result["protocol"] == "stateful"
    assert "protocol_degraded" not in result
