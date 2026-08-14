"""CardUnified — card type registry (config-driven, YAML-extensible).

Extracted from ``card_unified.py``: the process-wide card-type definition
registry (``register_card_type`` / ``get_card_type`` / ``list_card_types`` /
``load_card_types``) and the built-in registration seed.
"""

from __future__ import annotations

import threading

_card_type_registry: dict[str, dict] = {}
_registry_lock = threading.Lock()


def register_card_type(name: str, definition: dict) -> None:
    """Register a card type definition.

    YAML example:
      card_types:
        execution:
          display: "Execution Card"
          has_review: true
          phases: ["plan", "implement", "review"]
        issue:
          display: "Issue Card"
          has_review: false
          phases: ["discuss", "converge"]
    """
    with _registry_lock:
        _card_type_registry[name] = {
            "display": definition.get("display", name),
            "has_review": definition.get("has_review", False),
            "phases": list(definition.get("phases", [])),
            "default_prompts": dict(definition.get("default_prompts", {})),
            "metadata_schema": dict(definition.get("metadata_schema", {})),
        }


def get_card_type(name: str) -> dict:
    """Return the registered card type definition dict for a name."""
    with _registry_lock:
        return _card_type_registry.get(name, {})


def list_card_types() -> list[dict]:
    """List all registered card types (metadata dicts)."""
    with _registry_lock:
        return [{"name": k, **v} for k, v in _card_type_registry.items()]


def load_card_types(cfg: dict) -> None:
    """Load card type definitions from praxis.yaml → card_types: section."""
    if not cfg:
        return
    for name, defn in cfg.items():
        register_card_type(name, defn)


# ── Built-in card type registration ──


def _register_builtins() -> None:
    register_card_type(
        "execution",
        {
            "display": "Execution Card",
            "has_review": True,
            "phases": ["plan", "implement", "review"],
            "default_prompts": {
                "review": "Verify all changes implement the intent correctly.",
            },
            "metadata_schema": {
                "domain": {"type": "string", "default": "."},
                "risk": {"type": "choice", "options": ["low", "medium", "high"]},
            },
        },
    )
    register_card_type(
        "issue",
        {
            "display": "Issue Card",
            "has_review": False,
            "phases": ["discuss", "converge"],
            "default_prompts": {},
            "metadata_schema": {
                "domain": {"type": "string", "default": "."},
            },
        },
    )
    register_card_type(
        "review",
        {
            "display": "Review Card",
            "has_review": True,
            "phases": ["review"],
            "default_prompts": {
                "review": "Review the code for correctness, security, and style.",
            },
            "metadata_schema": {},
        },
    )
    register_card_type(
        "inspection",
        {
            "display": "Inspection Card",
            "has_review": False,
            "phases": ["inspect"],
            "default_prompts": {},
            "metadata_schema": {
                "target": {"type": "string"},
            },
        },
    )


_register_builtins()
