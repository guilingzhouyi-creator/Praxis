"""2.1-D4 tests — build/review model division (department → model_spec)."""

from __future__ import annotations

from l3.cell.department import model_role_for


def test_model_role_for_review_uses_high_model_executor():
    """Review departments resolve the 'review' executor (high model)."""
    assert model_role_for("review") == "review"


def test_model_role_for_build_and_test_share_low_model():
    """Build/test departments share the cheap 'build' executor (low model)."""
    assert model_role_for("build") == "build"
    assert model_role_for("test") == "build"


def test_model_role_for_unknown_falls_back():
    """Unknown department types fall back to the default executor."""
    assert model_role_for("custom") == "default"
    assert model_role_for("general") == "default"


def test_praxis_yaml_has_department_model_specs():
    """praxis.yaml declares model_spec.build and model_spec.review."""
    import yaml

    with open("config/praxis.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    specs = (cfg.get("model_spec") or {}).get("build", {}).get("defaults", {})
    review = (cfg.get("model_spec") or {}).get("review", {}).get("defaults", {})
    assert "max_tokens" in specs
    assert "max_tokens" in review
    # Review is the stronger executor (higher max_tokens / effort).
    assert review.get("max_tokens", 0) >= specs.get("max_tokens", 0)


def test_resolve_dict_accepts_build_review_spec_names():
    """model_service.resolve_dict handles the department spec names."""
    from l3.services.model_service import get_service

    svc = get_service()
    for spec in ("build", "review"):
        d = svc.resolve_dict(spec)
        assert isinstance(d, dict)
        assert "max_tokens" in d
