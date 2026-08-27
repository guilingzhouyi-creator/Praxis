"""LLM inference engine — provider-agnostic interface for agent thinking.

Each call goes through the kernel device manager for rate limiting.
Supports multiple providers: Claude, GPT, local, or mock (for testing).

Module layout (split for readability):
  llm_base.py      — LLMConfig / LLMProvider / ToolSearch base types
  llm_providers.py — provider implementations (Mock/WebSocket/…)
  llm_retry.py     — LLMRetryMixin (low-level HTTP call with retry)
  llm_tools.py     — LLMToolsMixin (tool format conversion + execution)
  llm_hooks.py     — pre/post call lifecycle hooks + token counter
  llm_engine.py    — LLMEngine class + LLMPort adapter + optimize_prompt
  llm.py           — singleton + convenience API (this facade)

Usage:
  from l4.llm.llm import think, analyze

  result = think("What is the capital of France?", system="You are a helpful assistant")
  # → {"content": "Paris", "tokens": 15, "model": "claude-3-haiku"}

  result = analyze("review this code", code_snippet, context="security audit")
  # → {"content": "Found 3 vulnerabilities...", "findings": [...]}
"""

from __future__ import annotations

import logging
import threading
from typing import cast

from l1.kernel.params.agent import LLM_ANALYZE_MAX_TOKENS
from l1.kernel.params.api import (
    DEFAULT_REASONING_EFFORT,
    DEFAULT_THINKING_BUDGET,
    FALLBACK_LLM_API_URL,
    FALLBACK_MODEL,
    LLM_DEFAULT_MAX_TOKENS,
)
from l1.kernel.params.system import LOG_TRUNC_60  # noqa: F401 — re-export

# Base types / mixins / engine re-exported so existing imports keep working.
from .llm_base import (  # noqa: F401 — re-export
    LLMConfig,
    LLMProvider,
    ToolSearch,
    register_provider,
)
from .llm_engine import LLMEngine, _register_llm_port, optimize_prompt  # noqa: F401 — re-export
from .llm_hooks import _LLM_HOOKS, on_llm_call  # noqa: F401 — re-export
from .llm_providers import MockProvider  # noqa: F401 — re-export
from .llm_retry import LLMRetryMixin  # noqa: F401 — re-export
from .llm_tools import LLMToolsMixin  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


# ── Module-level convenience ──

_engine: LLMEngine | None = None
_engine_lock = threading.Lock()


def get_engine(config: LLMConfig | None = None) -> LLMEngine:
    """Get or create the singleton LLMEngine instance."""
    global _engine
    if config is None:
        try:
            from l1.kernel.settings import get_settings

            s = get_settings()
            config = LLMConfig(
                provider=s.get("llm.provider", "mock"),
                model=s.get("llm.model", FALLBACK_MODEL),
                api_url=s.get("llm.api_url", FALLBACK_LLM_API_URL),
                api_key=s.get("llm.api_key", ""),
                max_tokens=s.get("llm.max_tokens", LLM_DEFAULT_MAX_TOKENS),
                temperature=s.get("llm.temperature", 0.3),
                reasoning_effort=s.get("llm.reasoning_effort", DEFAULT_REASONING_EFFORT),
                thinking_budget=s.get("llm.thinking_budget", DEFAULT_THINKING_BUDGET),
            )
        except Exception:
            config = LLMConfig()
    if _engine is None or _engine.config != config:
        with _engine_lock:
            if _engine is None or _engine.config != config:
                _engine = LLMEngine(config)
                _register_llm_port(_engine)
    return _engine


def reset_engine() -> None:
    """Reset the singleton LLMEngine (for testing)."""
    global _engine
    _engine = None


def think(prompt: str, system: str = "", max_tokens: int = LLM_DEFAULT_MAX_TOKENS, user_id: str = "") -> dict:
    """Convenience: one-shot LLM inference."""
    return get_engine().generate(prompt, system, max_tokens, user_id=user_id)


def analyze(findings: list, context: str = "", user_id: str = "") -> dict:
    """Analyze findings (scout results, code review, etc.) with LLM."""
    from l3.agent.prompts import get_prompt as _gp

    prompt = f"Context: {context}\n\nFindings:\n" + "\n".join(str(f) for f in findings)
    prompt += _gp("llm.analyze_suffix", "")
    return get_engine().generate(
        prompt,
        system=_gp("llm.analyze_system", "You are a code analysis expert."),
        max_tokens=LLM_ANALYZE_MAX_TOKENS,
        user_id=user_id,
    )


# ── Auto-register built-in providers by scanning llm_providers module ──
try:
    import importlib as _il
    import inspect as _inspect

    _prov_mod = _il.import_module(".llm_providers", __package__)
    for _name, _cls in _inspect.getmembers(_prov_mod, _inspect.isclass):
        # Duck-type check: any class with .name (str) and .generate() is a provider
        if hasattr(_cls, "name") and isinstance(getattr(_cls, "name", None), str) and hasattr(_cls, "generate"):
            register_provider(_cls.name, cast(type[LLMProvider], _cls), override=True)
except Exception as e:
    logger.warning("services/llm: %s", e)
