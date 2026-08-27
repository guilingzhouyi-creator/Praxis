"""LLM lifecycle hooks — pre/post call monitoring registry.

Extracted from ``llm.py``: the hook registry, the ``on_llm_call`` decorator
and the auto-wired token counter hook. Imported by the engine; re-exported
by ``llm.py`` so ``from l4.llm.llm import on_llm_call`` keeps working.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_LLM_HOOKS: dict[str, list] = {"pre": [], "post": []}


def on_llm_call(hook_type: str):
    """Decorator to register an LLM lifecycle hook.

    Args:
        hook_type: "pre" (before generate) or "post" (after generate)

    Pre-hooks receive: prompt, system, max_tokens, user_id, **kwargs
    Post-hooks receive: result (dict), **kwargs
    """

    def wrapper(fn):
        """Register a hook function and return it unchanged."""
        _LLM_HOOKS.setdefault(hook_type, []).append(fn)
        return fn

    return wrapper


# ── Auto-wire counter into post-call hook ──


@on_llm_call("post")
def _counter_hook(result, prompt="", system="", max_tokens=0, user_id="", **kwargs):
    try:
        from .services.counter import get_counter

        c = get_counter()
        inp = result.get("input_tokens", 0)
        out = result.get("output_tokens", 0)
        c.record_token(
            agent_id=user_id or "unknown",
            input_tokens=inp,
            output_tokens=out,
            cache_hit=result.get("cache_hit_tokens", 0),
            cache_miss=result.get("cache_miss_tokens", 0),
            model=result.get("model", ""),
        )
        # Also emit TOKEN_USAGE event for CentralCollector cross-Cell aggregation
        from l1.kernel import emit_signal

        provider = kwargs.get("provider", "")
        from l1.kernel.params.agent import EVENT_TOKEN_USAGE

        emit_signal(
            EVENT_TOKEN_USAGE,
            sender=user_id or "unknown",
            target="central_collector",
            data={
                "agent_id": user_id or "unknown",
                "cell_id": kwargs.get("cell_id", "default"),
                "input_tokens": inp,
                "output_tokens": out,
                "provider": provider,
                "model": result.get("model", ""),
            },
        )
    except Exception as e:
        logger.warning("services/llm: %s", e)
