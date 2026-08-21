"""L2 Shell: model and settings commands (config, cron, model, settings)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from l2.bridge import capture
from l2.i18n import t as _t

logger = logging.getLogger(__name__)


def _cmd_config(args: list[str], session=None) -> dict:
    from l1.kernel.settings import get_settings
    from l2.bridge import settings_set

    s = get_settings()
    if not args:
        return {"success": True, "settings": s.all()}
    if args[0] == "set" and len(args) >= 3:
        key, value = args[1], _coerce_str(args[2])
        settings_set(key, value)
        return {"success": True, "key": key, "value": value}
    v = s.get(args[0])
    return {"success": True, args[0]: v}


def _cmd_cron(args: list[str], session=None) -> dict:
    from l4.cron_scheduler import get_scheduler

    s = get_scheduler()
    sub = args[0].lower() if args else "list"
    if sub == "list":
        return {"success": True, "cron": s.list()}
    if sub == "add" and len(args) >= 4:
        return {"success": True, "id": args[1], "schedule": args[2], "task": args[3]}
    return {"success": False, "error": _t("shell.app_error.usage_cron")}


def _model_switch_cmd(args: list[str]) -> dict:
    """Handle `model switch <name> <provider> [model]` with arg guard."""
    if len(args) < 3:
        return {"success": False, "error": _t("shell.app_error.usage_model")}
    return _model_switch(args[1], args[2], args[3] if len(args) > 3 else "")


def _model_set_cmd(args: list[str]) -> dict:
    """Handle `model set <k> <v> <scope>` with arg guard."""
    if len(args) < 4:
        return {"success": False, "error": _t("shell.app_error.usage_model")}
    return _model_set(args[1], args[2], args[3])


_MODEL_HANDLERS: dict[str, Callable[[list[str]], dict]] = {
    "list": lambda args: _model_list(),
    "status": lambda args: _model_status(),
    "switch": _model_switch_cmd,
    "health": lambda args: _model_health(args[1] if len(args) > 1 else ""),
    "set": _model_set_cmd,
    "spec": lambda args: _cmd_model_spec(args[1:]),
}


def _cmd_model(args: list[str], session=None) -> dict:
    if not args:
        return _model_list()
    handler = _MODEL_HANDLERS.get(args[0].lower())
    if not handler:
        return {"success": False, "error": _t("shell.app_error.usage_model")}
    return handler(args)


def _model_spec_caps(args: list[str]) -> dict:
    """Handle `model spec caps [max_reasoning] [max_budget]`."""
    from l4.api_handlers.api_handlers_providers import handle_think_caps_get, handle_think_caps_set

    if len(args) < 2:
        return handle_think_caps_get({})
    caps: dict[str, object] = {"max_reasoning": args[1]}
    if len(args) >= 3:
        try:
            caps["max_budget"] = int(args[2])
        except ValueError:
            return {"success": False, "error": _t("shell.app_error.model_budget_int")}
    return handle_think_caps_set(caps)


def _cmd_model_spec(args: list[str], session=None) -> dict:
    """Model-spec / strategy panel: view, switch packs, set caps."""
    from l2.bridge import model_apply_strategy, model_clear_strategy
    from l4.api_handlers.api_handlers_providers import handle_model_spec_overview

    if not args:
        return handle_model_spec_overview({})
    sub = args[0].lower()
    if sub == "strategy" and len(args) >= 3:
        return model_apply_strategy(args[1], args[2])
    if sub == "clear" and len(args) >= 2:
        return model_clear_strategy(args[1])
    if sub == "caps":
        return _model_spec_caps(args)
    if sub == "peer":
        return _cmd_model_spec_peer(args[1:])
    return {
        "success": False,
        "error": _t("shell.app_error.usage_model_spec"),
    }


def _cmd_model_spec_peer(args: list[str], session=None) -> dict:
    """Peer-agent think strategy: apply/clear strategy packs on think scopes."""
    from l2.bridge import think_apply_strategy, think_clear_strategy
    from l4.api_handlers.api_handlers_providers import handle_peer_strategy_get

    if not args:
        return handle_peer_strategy_get({})
    sub = args[0].lower()
    if sub == "clear" and len(args) >= 3:
        return think_clear_strategy(args[1], args[2])
    if sub in ("global", "cell", "agent") and len(args) >= 2:
        if sub == "global":
            return think_apply_strategy("global", "", args[1])
        if len(args) >= 3:
            return think_apply_strategy(sub, args[1], args[2])
        return {"success": False, "error": _t("shell.app_error.usage_model_spec_peer_sub", sub=sub)}
    return {
        "success": False,
        "error": _t("shell.app_error.usage_model_spec_peer"),
    }


def _cmd_settings(args: list[str], session=None) -> dict:
    from .commands_settings import _cmd_settings as _cs

    return _cs(args)


def _coerce_str(v: str) -> Any:
    try:
        return int(v)
    except ValueError:
        logger.debug("model: %r not an int, trying float", v)
    try:
        return float(v)
    except ValueError:
        logger.debug("model: %r not numeric, returning string", v)
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    return v


def _model_list() -> dict:
    from l1.kernel.params.agent import AGENT_ROLE_TYPES
    from l2.bridge import model_resolve

    lines = [f"Providers ({len(AGENT_ROLE_TYPES)} registered):"]
    for role in AGENT_ROLE_TYPES:
        try:
            cfg = model_resolve(role)
            lines.append(f"  {role:25s} → provider={cfg['provider']:15s} model={cfg['model']}")
        except Exception:
            capture("model: resolve failed", error_code="E_CMD", component="l2", context={"role": role})
            lines.append(f"  {role:25s} → (error)")
    return {"success": True, "output": "\n".join(lines)}


def _model_switch(role: str, provider: str, model: str = "") -> dict:
    from l1.kernel.params.agent import AGENT_CLEARANCE
    from l2.bridge import settings_set

    if role not in AGENT_CLEARANCE:
        return {"success": False, "error": _t("shell.app_error.unknown_role", role=role)}
    prefix = f"model.{role}"
    settings_set(f"{prefix}.provider", provider)
    if model:
        settings_set(f"{prefix}.model", model)
    try:
        from l1.kernel import get_event_bus

        get_event_bus().emit_event("settings.updated", data={"key": prefix, "provider": provider, "model": model})
    except Exception:
        capture("model: event emit failed", error_code="E_CMD", component="l2", context={"role": role})
        logger.warning("_cmd_model: failed to emit settings.updated event")
    return {"success": True, "role": role, "provider": provider, "model": model}


def _model_status() -> dict:
    return {"success": True, "note": "use /model list"}


def _model_health(provider: str = "") -> dict:
    from l2.bridge import model_providers

    try:
        from l4.llm.llm import get_engine

        engine = get_engine()
        if hasattr(engine._provider, "health"):
            return engine._provider.health()
    except Exception:
        capture("model: health check failed", error_code="E_CMD", component="l2")
    return {"success": True, "providers": model_providers()}


def _model_set(role: str, key: str, value: str) -> dict:
    from l2.bridge import settings_set

    prefix = f"model.{role}"
    settings_set(f"{prefix}.{key}", _coerce_str(value))
    return {"success": True, f"{prefix}.{key}": value}
