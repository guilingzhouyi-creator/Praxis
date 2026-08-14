"""State isolation guards — global singletons must not leak across tests.

Module-level mutable state (locale, skill usage counters, ports) needs a
reset before every test. These tests verify the most leak-prone ones are
covered by tests/conftest.py and actually isolated, so the "passes alone,
fails in parallel" class of CI breakage stays fixed.
"""

from __future__ import annotations

import l1.kernel.errors as errors_mod
import tests.conftest as conftest
from l1.kernel.skill import get_skill_manager, reset_skill_manager


class TestResetCoverage:
    """_RESETS (plus fixture-level resets) must cover the leak-prone modules."""

    def test_resets_cover_locale_and_skill_state(self):
        resets = set(conftest._RESETS)
        assert "l1.kernel.errors" in resets  # error handler; locale reset lives in the fixture
        assert "l1.kernel.skill" in resets  # SkillManager usage counters / bindings
        assert "l3.memory.skill_retriever" in resets  # tf-idf corpus

    def test_errors_module_exposes_locale_reset(self):
        assert callable(errors_mod.reset_locale)


class TestLocaleIsolation:
    """i18n locale state is reset before every test (autouse fixture)."""

    def test_locale_not_leaked_from_previous_test(self):
        # Any earlier test that called set_locale("zh-CN") would fail this
        # unless the autouse fixture reset the module-level locale.
        assert errors_mod.get_locale() == "en"

    def test_setting_locale_is_isolated(self):
        errors_mod.set_locale("zh-CN")
        assert errors_mod.get_locale() == "zh-CN"

    def test_port_adapter_locale_is_reset(self):
        """reset_locale must also clear a registered i18n adapter's locale."""
        from l1.kernel.ports import _PORTS
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        saved = _PORTS.pop("i18n", None)
        try:
            adapter = YamlI18nAdapter(locale_dir="locales")
            _PORTS["i18n"] = adapter
            adapter.set_locale("zh-CN")
            assert adapter.get_locale() == "zh-CN"
            errors_mod.reset_locale()
            assert adapter.get_locale() == "en"
        finally:
            if saved is not None:
                _PORTS["i18n"] = saved
            else:
                _PORTS.pop("i18n", None)


class TestSkillManagerIsolation:
    """SkillManager usage counters are reset before every test."""

    def test_usage_counters_do_not_leak(self):
        reset_skill_manager()
        sm = get_skill_manager()
        sm.load_dir("config/skills")
        sm.bump_usage("kernel")
        skill = sm.get("kernel")
        assert (skill.get("useful_count") or 0) >= 1
        # The autouse fixture resets after this test, so a later test sees 0.
