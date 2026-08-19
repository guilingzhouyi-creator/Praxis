"""Cache strategy tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCacheStrategy:
    def test_importable(self):
        from l3.config.cache_strategy import ConfigCacheStrategy

        assert callable(ConfigCacheStrategy)


class TestResolveCacheFlags:
    def test_pure_merge_adds_missing_keys(self):
        """Probe capability keys fill gaps; explicit config always wins."""
        from l1.kernel.params.system import CACHE_CAP_PREFIX_CACHE, CACHE_CAP_STATEFUL, CACHE_CAP_USER_ID
        from l3.config.cache_strategy import resolve_cache_flags

        cfg = {"optimize_prompt": True, "protocol": "stateful"}
        probe = {CACHE_CAP_STATEFUL: False, CACHE_CAP_PREFIX_CACHE: True, CACHE_CAP_USER_ID: True}
        merged = resolve_cache_flags(cfg, probe)
        assert merged["protocol"] == "stateful"
        assert merged["optimize_prompt"] is True
        assert merged["forward_user_id"] is True
        assert not any(k.startswith("supports_") for k in merged)

    def test_pure_merge_respects_probe_when_unconfigured(self):
        """A probe-only key maps onto the config flag vocabulary."""
        from l1.kernel.params.system import CACHE_CAP_PREFIX_CACHE
        from l3.config.cache_strategy import resolve_cache_flags

        merged = resolve_cache_flags({}, {CACHE_CAP_PREFIX_CACHE: False})
        assert merged["optimize_prompt"] is False

    def test_pure_merge_ignores_unknown_keys(self):
        """Unknown probe keys never leak into the strategy options."""
        from l3.config.cache_strategy import resolve_cache_flags

        merged = resolve_cache_flags({}, {"something_else": True})
        assert merged == {}


class TestRefreshStrategy:
    def test_refresh_applies_once_and_is_idempotent(self):
        """Repeated probes with the same fingerprint cause no churn."""
        from l1.kernel.params.system import CACHE_CAP_STATEFUL
        from l3.config import cache_strategy as cs

        cs.reset_cache_strategy()
        try:
            cs.load_cache_config({"defaults": {"refresh_enabled": True}})
            probe = {CACHE_CAP_STATEFUL: True}
            first = cs.refresh_strategy("openai", probe)
            assert first["applied"] is True
            assert first["opts"]["protocol"] == "stateful"
            second = cs.refresh_strategy("openai", probe)
            assert second["applied"] is False
            assert second["reason"] == "unchanged"
        finally:
            cs.reset_cache_strategy()

    def test_refresh_respects_master_switch(self):
        """The refresh loop is gated by llm.cache.defaults.refresh_enabled."""
        from l1.kernel.params.system import CACHE_CAP_STATEFUL
        from l3.config import cache_strategy as cs

        cs.reset_cache_strategy()
        try:
            cs.load_cache_config({"defaults": {"refresh_enabled": False}})
            r = cs.refresh_strategy("openai", {CACHE_CAP_STATEFUL: True})
            assert r["applied"] is False
            assert r["reason"] == "refresh disabled"
        finally:
            cs.reset_cache_strategy()

    def test_refresh_requires_capability_keys(self):
        """A probe without CACHE_CAP_* keys is a no-op."""
        from l3.config import cache_strategy as cs

        cs.reset_cache_strategy()
        try:
            cs.load_cache_config({"defaults": {"refresh_enabled": True}})
            r = cs.refresh_strategy("openai", {"supports": {"max_tokens"}})
            assert r["applied"] is False
            assert r["reason"] == "probe has no capability keys"
        finally:
            cs.reset_cache_strategy()

    def test_refresh_changes_fingerprint_applies_again(self):
        """A changed probe fingerprint refreshes the strategy."""
        from l1.kernel.params.system import CACHE_CAP_PREFIX_CACHE, CACHE_CAP_STATEFUL
        from l3.config import cache_strategy as cs

        cs.reset_cache_strategy()
        try:
            cs.load_cache_config({"defaults": {"refresh_enabled": True}})
            assert cs.refresh_strategy("deepseek", {CACHE_CAP_STATEFUL: True})["applied"] is True
            r = cs.refresh_strategy("deepseek", {CACHE_CAP_STATEFUL: True, CACHE_CAP_PREFIX_CACHE: False})
            assert r["applied"] is True
            assert r["opts"]["optimize_prompt"] is False
        finally:
            cs.reset_cache_strategy()
