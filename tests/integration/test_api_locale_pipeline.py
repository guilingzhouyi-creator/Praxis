"""API locale pipeline — query locale flows middleware → handler intact.

Registers a real I18nPort (locales/) so the LocaleMiddleware's availability
check and port fallback are exercised against production data, not just
standalone middleware units (parallel-isolation history: a polluted port
locale used to make the chain assertion order-dependent).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def _i18n_port():
    """Register a real YamlI18nAdapter on the i18n port, then restore."""
    from l1.kernel.ports import _PORTS
    from l4.adapters.i18n_yaml import YamlI18nAdapter

    saved = _PORTS.pop("i18n", None)
    _PORTS["i18n"] = YamlI18nAdapter(locale_dir="locales")
    yield
    if saved is not None:
        _PORTS["i18n"] = saved
    else:
        _PORTS.pop("i18n", None)


class TestApiLocalePipeline:
    """Locale from ?locale= reaches the handler through the full chain."""

    def test_query_locale_reaches_handler(self, _i18n_port):
        from l4.api.api_middleware import LocaleMiddleware, MiddlewareChain, Request

        chain = MiddlewareChain([LocaleMiddleware()])

        def handler(r):
            return {"status": "ok", "locale": r.locale}

        resp = chain.handle(Request(method="GET", path="/api/x", query={"locale": "ja"}), handler)
        assert resp.data.get("locale") == "ja"

    def test_missing_query_falls_back_to_port_locale(self, _i18n_port):
        from l1.kernel.errors import set_locale
        from l4.api.api_middleware import LocaleMiddleware, MiddlewareChain, Request

        set_locale("zh-CN")  # port's current locale drives the fallback
        chain = MiddlewareChain([LocaleMiddleware()])

        def handler(r):
            return {"status": "ok", "locale": r.locale}

        resp = chain.handle(Request(method="GET", path="/api/x"), handler)
        assert resp.data.get("locale") == "zh-CN"
