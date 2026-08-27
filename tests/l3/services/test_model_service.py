"""Model service tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "systems/python-reference-runtime"))


class TestModelService:
    def test_importable(self):
        from l3.services.model_service import get_service

        svc = get_service()
        assert svc is not None


class TestResolveForDepartment:
    """2.1-D4 — department → model config is config-driven, never hardcoded."""

    def test_resolve_returns_dict(self):
        from l3.services.model_service import get_service

        out = get_service().resolve_for_department("review")
        assert isinstance(out, dict)

    def test_department_mapping_is_config_data(self):
        """review/build map to their model_spec executors (not hardcoded models)."""
        from l3.cell.department import model_role_for

        assert model_role_for("review") == "review"
        assert model_role_for("build") == "build"
        assert model_role_for("test") == "build"
        assert model_role_for("custom") == "default"
        assert model_role_for("general") == "default"

    def test_unknown_department_degrades(self):
        from l3.services.model_service import get_service

        # "custom" is a valid DEPARTMENT_TYPES entry; unknown types fall back
        # to the default executor and still return a dict (never raise).
        out = get_service().resolve_for_department("does-not-exist")
        assert isinstance(out, dict)
