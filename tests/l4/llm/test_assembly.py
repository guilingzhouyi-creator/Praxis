"""Provider assembly factory + protocol selection tests (3.1 G1/G2)."""

from __future__ import annotations


def test_default_assembler_builds_system_user_messages():
    from l4.llm.assembly import assemble_messages, reset_assembly

    reset_assembly()
    try:
        msgs = assemble_messages("openai", "hello", system="sys")
        assert msgs == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]
    finally:
        reset_assembly()


def test_register_assembler_override():
    from l4.llm.assembly import assemble_messages, register_assembler, reset_assembly

    reset_assembly()
    try:
        register_assembler("custom", lambda p, s="", **kw: [{"role": "user", "content": f"CUSTOM:{p}"}])
        msgs = assemble_messages("custom", "hi")
        assert msgs == [{"role": "user", "content": "CUSTOM:hi"}]
    finally:
        reset_assembly()


def test_protocol_registry_set_and_get():
    from l4.llm.assembly import get_protocol, reset_assembly, set_protocol

    reset_assembly()
    try:
        assert get_protocol("openai") is None  # unset
        set_protocol("openai", "stateful")
        assert get_protocol("openai") == "stateful"
        set_protocol("openai", "bogus")  # invalid ignored
        assert get_protocol("openai") == "stateful"
    finally:
        reset_assembly()


def test_cache_strategy_protocol_default_stateless():
    from l3.config.cache_strategy import ConfigCacheStrategy

    assert ConfigCacheStrategy("openai").protocol == "stateless"


def test_engine_protocol_resolution_registry_first():
    from l4.llm.assembly import reset_assembly, set_protocol
    from l4.llm.llm_engine import LLMEngine

    reset_assembly()
    try:
        engine = LLMEngine()
        engine.config = engine.config.__class__(provider="openai")
        assert engine._get_protocol() == "stateless"  # config default
        set_protocol("openai", "stateful")
        assert engine._get_protocol() == "stateful"  # registry override wins
    finally:
        reset_assembly()
