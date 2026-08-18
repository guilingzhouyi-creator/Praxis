"""Config-file driven persistence tests for L3A compression switches (3.1, G3).

Verifies the four operator-switch modules (digest / tool-result offload /
sensitive detection / compression guard) read their initial value from the
settings facade (l1.kernel.settings -> SettingsCenter) and persist runtime
API/L2 writes, so a restart picks up the operator override.
"""

from __future__ import annotations


def test_settings_defaults_register_compression_keys():
    """l1.kernel.settings.DEFAULTS carries the seven 3.1 switch defaults."""
    from l1.kernel.params.system import (
        COMPRESSION_BREAKER_ENABLED_DEFAULT,
        COMPRESSION_RECURSION_THRESHOLD_DEFAULT,
        DIGEST_ENABLED_DEFAULT,
        DIGEST_MAX_CHARS_DEFAULT,
        SENSITIVE_DETECT_ENABLED_DEFAULT,
        TOOL_RESULT_OFFLOAD_ENABLED_DEFAULT,
        TOOL_RESULT_OFFLOAD_MAX_CHARS_DEFAULT,
    )
    from l1.kernel.settings import DEFAULTS

    assert DEFAULTS["l3a.digest.enabled"] == DIGEST_ENABLED_DEFAULT
    assert DEFAULTS["l3a.digest.max_chars"] == DIGEST_MAX_CHARS_DEFAULT
    assert DEFAULTS["l3a.tool_result.enabled"] == TOOL_RESULT_OFFLOAD_ENABLED_DEFAULT
    assert DEFAULTS["l3a.tool_result.max_chars"] == TOOL_RESULT_OFFLOAD_MAX_CHARS_DEFAULT
    assert DEFAULTS["l3a.sensitive.enabled"] == SENSITIVE_DETECT_ENABLED_DEFAULT
    assert DEFAULTS["l3a.compression_guard.recursion_threshold"] == COMPRESSION_RECURSION_THRESHOLD_DEFAULT
    assert DEFAULTS["l3a.compression_guard.breaker_enabled"] == COMPRESSION_BREAKER_ENABLED_DEFAULT


def test_digest_switch_set_persists_and_reset_clears():
    from l1.kernel.settings import get_settings, reset_settings
    from l3.agent.digest_cache import digest_status, reset_digest, set_digest_switches

    reset_digest()
    reset_settings()
    try:
        set_digest_switches(enabled=True, max_chars=777)
        assert digest_status()["enabled"] is True
        assert digest_status()["max_chars"] == 777
        assert get_settings().get("l3a.digest.enabled") is True
        assert get_settings().get("l3a.digest.max_chars") == 777
        reset_digest()
        assert digest_status()["enabled"] is True
        assert digest_status()["max_chars"] == 400
    finally:
        reset_digest()
        reset_settings()


def test_digest_hydrates_from_preseeded_config():
    from l1.kernel.settings import get_settings, reset_settings
    from l3.agent.digest_cache import digest_status, reset_digest

    reset_digest()
    reset_settings()
    try:
        get_settings().set("l3a.digest.max_chars", 1234)
        # _hydrated is already False from the top reset_digest(), so the next
        # status read re-hydrates from the preseeded config value.
        assert digest_status()["max_chars"] == 1234
    finally:
        reset_digest()
        reset_settings()


def test_guard_switch_persists_and_reset_clears():
    from l1.kernel.settings import get_settings, reset_settings
    from l3.agent.compression_guard import guard_status, reset_guard, set_guard_switches

    reset_guard()
    reset_settings()
    try:
        set_guard_switches(recursion_threshold=5, breaker_enabled=False)
        assert guard_status()["recursion_threshold"] == 5
        assert guard_status()["breaker_enabled"] is False
        assert get_settings().get("l3a.compression_guard.recursion_threshold") == 5
        reset_guard()
        assert guard_status()["recursion_threshold"] == 0
        assert guard_status()["breaker_enabled"] is True
    finally:
        reset_guard()
        reset_settings()


def test_sensitive_switch_persists_and_reset_clears():
    from l1.kernel.settings import get_settings, reset_settings
    from l3.agent.sensitive_detect import reset_sensitive, sensitive_status, set_sensitive_switches

    reset_sensitive()
    reset_settings()
    try:
        set_sensitive_switches(enabled=False)
        assert sensitive_status()["enabled"] is False
        assert get_settings().get("l3a.sensitive.enabled") is False
        reset_sensitive()
        assert sensitive_status()["enabled"] is True
    finally:
        reset_sensitive()
        reset_settings()


def test_tool_result_switch_persists_and_reset_clears():
    from l1.kernel.settings import get_settings, reset_settings
    from l3.agent.tool_result_cache import reset_tool_result, set_tool_result_switches, tool_result_status

    reset_tool_result()
    reset_settings()
    try:
        set_tool_result_switches(enabled=False, max_chars=999)
        assert tool_result_status()["enabled"] is False
        assert tool_result_status()["max_chars"] == 999
        assert get_settings().get("l3a.tool_result.enabled") is False
        reset_tool_result()
        assert tool_result_status()["enabled"] is True
        assert tool_result_status()["max_chars"] == 4000
    finally:
        reset_tool_result()
        reset_settings()
