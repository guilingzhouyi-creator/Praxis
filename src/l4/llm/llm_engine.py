"""LLM inference engine — provider-agnostic interface for agent thinking.

Extracted from ``llm.py``: the LLMEngine class (generate / generate_with_cache
/ embed / tool_use), the LLMPort adapter registration and the prompt
optimizer. The module-level singleton and convenience API (``think`` /
``analyze`` / ``get_engine``) stay in ``llm.py``; lifecycle hooks live in
``llm_hooks.py``.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, cast

from l1.kernel.device import get_device_manager
from l1.kernel.discovery import get_tool_config
from l1.kernel.params.agent import (
    LLM_CACHE_RETENTION_STRING,
    LLM_CACHE_RETENTION_THRESHOLD,
    LLM_THINKING_BUFFER,
    LLM_TOOL_RESULT_TRUNCATION,
    LOOP_TURN_WARNING_THRESHOLD,
)
from l1.kernel.params.api import (
    FALLBACK_MODEL,
)
from l1.kernel.params.system import CONTEXT_TRAIL_TRUNC, HASH_TRUNC_SHORT
from l1.kernel.params.system import TOOL_SEARCH_MAX_RESULTS as _TOOL_SEARCH_MAX_RESULTS
from l1.kernel.params.system import TOOL_SEARCH_MIN_COUNT as _TOOL_SEARCH_MIN_COUNT
from l1.kernel.params.tool import TOOL_HANDLER_TIMEOUT as _TOOL_HANDLER_TIMEOUT
from l1.kernel.prompts import get_prompt as _gp

# Resolve tool config at module level (lazy-safe: discovery may not be ready at import)
_LLM_TOOL_TIMEOUT = get_tool_config("handler_timeout", _TOOL_HANDLER_TIMEOUT) or _TOOL_HANDLER_TIMEOUT

# Base types extracted to llm_base.py (mid-file imports avoid circularity)
from l3.tool_system.tool_spec import ToolSpec  # noqa: E402, I001

from .assembly import assemble_messages, get_protocol  # noqa: E402, I001
from .llm_base import (  # noqa: E402, I001
    LLMConfig,
    LLMProvider,
    ToolSearch,
)
from .llm_hooks import _LLM_HOOKS  # noqa: E402, I001
from .llm_providers import MockProvider  # noqa: E402, I001
from .llm_retry import LLMRetryMixin  # noqa: E402, I001
from .llm_tools import LLMToolsMixin  # noqa: E402, I001

logger = logging.getLogger(__name__)


class LLMEngine(LLMToolsMixin, LLMRetryMixin):
    """Inference engine — routes prompts to the configured provider.

    Composed from two same-layer mixins: ``llm_tools`` (tool format
    conversion + single-tool execution) and ``llm_retry`` (low-level HTTP
    call with layered retry).
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._provider = self._build_provider()
        self._http_opener = self._build_http_opener()

    @staticmethod
    def _build_http_opener():
        """Build a shared HTTP opener with keep-alive for connection reuse."""
        import urllib.request as req

        return req.build_opener()

    def _get_strategy(self):
        from l3.config.cache_strategy import get_strategy

        return get_strategy(self.config.provider)

    def _get_protocol(self, supports_stateful: bool | None = None) -> str:
        """Resolve the wire protocol (runtime registry > config > stateless default).

        ``auto`` is resolved by probing the active provider for native
        message-list support (``generate_with_messages``) via the pure
        ``resolve_protocol`` decision function — TS-equivalent portable.
        ``supports_stateful`` may be passed in from the caller to avoid a
        duplicate capability check on the hot path.
        """
        protocol = ""
        with contextlib.suppress(Exception):
            protocol = get_protocol(self.config.provider) or ""
        if not protocol:
            with contextlib.suppress(Exception):
                strategy = self._get_strategy()
                candidate = getattr(strategy, "protocol", None)
                if candidate in ("stateless", "stateful", "auto"):
                    protocol = str(candidate)
        if not protocol:
            protocol = "stateless"
        if supports_stateful is None:
            supports_stateful = self._provider_supports_stateful()
        return resolve_protocol(protocol, supports_stateful)

    def _provider_supports_stateful(self) -> bool:
        """Return whether the active provider implements message-list generation."""
        return bool(hasattr(self._provider, "generate_with_messages"))

    def _maybe_refresh_cache_strategy(self) -> None:
        """Refresh the prefix-cache strategy from the provider capabilities.

        Runtime capability set → strategy refresh loop (3.1, P1-3): the
        provider's static ``capabilities`` set is mapped onto the CACHE_CAP_*
        keys by the pure ``normalize_probe`` resolver; repeated refreshes with
        the same fingerprint are no-ops. Cheap (no network probe, no lock in
        the steady state) and never raises.
        """
        caps = getattr(self._provider, "capabilities", None)
        if not caps:
            return
        try:
            from l3.config.cache_strategy import refresh_strategy

            refresh_strategy(self.config.provider, {"supports": caps})
        except Exception:
            logger.debug("llm: cache strategy refresh skipped")

    def context_window(self, cell_id: str = "", agent_id: str = "") -> int:
        """Query the effective context window for the current provider+model.

        Resolution chain:
          1. ModelStrategyEngine.resolve() → check strategy config for context_window
          2. CapabilityDetector probe cache → detected context_window
          3. Return 0 = unknown (no compression, caller uses fallback)

        Args:
            cell_id: Cell identifier for strategy resolution.
            agent_id: Agent identifier for strategy resolution.
        """
        try:
            from l3.services.model_strategy import get_engine as _strat

            strat = _strat()
            pname = getattr(self._provider, "name", "")
            pmodel = getattr(self._provider, "model", "")
            resolved = strat.resolve(cell_id, agent_id, provider_name=pname, model=pmodel)
            cw = resolved.get("context_window", 0)
            return cw if cw > 0 else 0
        except Exception:
            return 0

    def _build_provider(self) -> LLMProvider:
        """Construct a provider instance using ModelRegistry.

        Falls back to MockProvider if no matching provider is found.
        """
        from l1.kernel.model_registry import get_registry

        p = self.config.provider
        if self.config.use_websocket:
            from .llm_providers import WebSocketProvider

            return cast(LLMProvider, WebSocketProvider(self.config.api_url, self.config.model))

        registry = get_registry()
        provider = registry.build_provider(
            provider=p,
            model=self.config.model,
            api_key=self.config.api_key,
            api_url=self.config.api_url,
            cache_breakpoints=self.config.cache_breakpoints,
        )
        if provider is not None:
            return provider

        logger.warning("llm: no provider '%s', using MockProvider", p)
        return cast(LLMProvider, MockProvider())

    def _apply_strategy(self, overrides: dict) -> dict:
        """Apply ModelStrategyEngine filtering: remove params the provider doesn't support.

        Also normalizes reasoning_effort to the provider's supported tier set
        (fall back to the highest supported tier at or below the requested
        one; lowest supported tier when the request is below all; drop the
        param entirely when the provider has no effort support).
        """
        try:
            from l3.services.model_strategy import get_engine as _strat

            strat = _strat()
            provider_name = getattr(self._provider, "name", "")
            model = getattr(self._provider, "model", "")
            filtered = strat.resolve("", "", provider_name=provider_name, model=model)
            # Take only strategy keys from filtered; keep override keys
            for k in filtered:
                if k in overrides:
                    filtered[k] = overrides[k]
            return self._normalize_effort(filtered, provider_name)
        except Exception:
            return overrides

    @staticmethod
    def _normalize_effort(params: dict, provider_name: str) -> dict:
        """Clamp reasoning_effort into the provider's supported tier set.

        Tier sets come from the ``llm.effort_tiers`` setting (praxis.yaml,
        per-provider flat keys) or the static defaults in params/api.py.
        Providers absent from both tables are left untouched.
        """
        effort = params.get("reasoning_effort")
        if not effort:
            return params
        try:
            from l1.kernel.params.api import EFFORT_RANK, EFFORT_TIERS_BY_PROVIDER
            from l3.config.settings_center import get_center

            sc = get_center()
            tiers = sc.get("llm.effort_tiers." + provider_name)
            if tiers is None:
                for key, value in sc.all().items():
                    if key.startswith("llm.effort_tiers." + provider_name + "."):
                        tiers = value
                        break
            if tiers is None:
                tiers = EFFORT_TIERS_BY_PROVIDER.get(provider_name)
                if tiers is None:
                    return params  # unknown provider: leave untouched
            tiers = list(tiers or ())
        except Exception:
            return params
        if not tiers:
            # Provider has no reasoning_effort support: drop the param
            params.pop("reasoning_effort", None)
            return params
        if effort in tiers:
            return params
        request_rank = EFFORT_RANK.get(effort, 0)
        below = [t for t in tiers if EFFORT_RANK.get(t, 0) <= request_rank]
        if below:
            params["reasoning_effort"] = max(below, key=lambda t: EFFORT_RANK.get(t, 0))
        else:
            params["reasoning_effort"] = min(tiers, key=lambda t: EFFORT_RANK.get(t, 0))
        logger.debug(
            "llm: reasoning_effort %r normalized to %r for %s", effort, params["reasoning_effort"], provider_name
        )
        return params

    def generate(
        self, prompt: str, system: str = "", max_tokens: int | None = None, user_id: str = "", **overrides: Any
    ) -> dict:
        """Generate a plain-text response from the LLM (no tool calls)."""
        dm = get_device_manager()
        r = dm.check_rate(self.config.device_name)
        if r.get("error", "").startswith("unknown device"):
            pass
        elif not r.get("allowed"):
            wait = r.get("reset_after", 1)
            logger.warning("LLM rate limited, waiting %.1fs", wait)
            time.sleep(wait)

        mt = max_tokens or self.config.max_tokens

        # P1-3: runtime provider-capability → cache-strategy refresh (idempotent).
        # Runs before strategy/protocol resolution so this very call already
        # benefits from the capability-merged flags (no-lock steady state).
        self._maybe_refresh_cache_strategy()

        # Pre-call hooks
        hook_kwargs = {"prompt": prompt, "system": system, "max_tokens": mt, "user_id": user_id}
        for hook in _LLM_HOOKS.get("pre", []):
            try:
                hook(**hook_kwargs)
            except Exception as e:
                logger.warning("services/llm: %s", e)

        prompt, system, cache_extra = self._get_strategy().optimize(prompt, system, user_id)
        merged = {
            **cache_extra,
            **overrides,
            "reasoning_effort": overrides.get("reasoning_effort", self.config.reasoning_effort),
            "thinking_budget": overrides.get("thinking_budget", self.config.thinking_budget),
        }
        # Filter by provider capabilities
        strategy_params = self._apply_strategy(merged)

        # Phase 3.1 G1/G2: protocol selection — stateful uses the pluggable
        # assembly factory (assemble_messages) + native message-list call;
        # stateless (default) keeps the historical per-provider splicing.
        # P1-2: a provider without native message-list support degrades to
        # the stateless wire path with the reason surfaced on the result.
        supports_stateful = self._provider_supports_stateful()
        protocol = self._get_protocol(supports_stateful)
        if protocol == "stateful" and supports_stateful:
            fallback = str(_gp("llm.fallback_system", "You are a helpful assistant."))
            messages = assemble_messages(self.config.provider, prompt, system, fallback_system=fallback)
            result = self._provider.generate_with_messages(
                messages,
                max_tokens=mt,
                user_id=user_id,
                cache_retention=self.config.cache_retention,
            )
            result["protocol"] = "stateful"
        else:
            if protocol == "stateful":
                logger.warning(
                    "llm: provider %r lacks generate_with_messages — degraded to stateless wire path",
                    self.config.provider,
                )
            result = self._provider.generate(
                prompt,
                system,
                mt,
                user_id=user_id,
                cache_retention=self.config.cache_retention,
                **strategy_params,
            )
            result["protocol"] = "stateless"
            if protocol == "stateful":
                result["protocol_degraded"] = True
                result["protocol_degrade_reason"] = "provider lacks generate_with_messages"

        # Post-call hooks
        for hook in _LLM_HOOKS.get("post", []):
            try:
                hook(result=result, **hook_kwargs)
            except Exception as e:
                logger.warning("LLM post-hook failed: %s", e)

        dm.record_call(self.config.device_name, success="error" not in result)
        return result

    def generate_with_cache(
        self, prompt: str, system: str = "", max_tokens: int | None = None, user_id: str = ""
    ) -> dict:
        """Generate with KV cache tracking. Pass user_id for per-agent cache isolation.

        DeepSeek: user_id maps to agent_id → independent KV cache namespace.
        Returns cache hit/miss tokens alongside response.
        """
        result = self.generate(prompt, system, max_tokens, user_id=user_id)
        # Ensure cache stats are present (providers may already populate them)
        if "cache_hit_tokens" not in result:
            result["cache_hit_tokens"] = 0
        if "cache_miss_tokens" not in result:
            # Use input_tokens (prompt tokens only, not total) for accurate miss count
            input_tokens = result.get("input_tokens", result.get("tokens", len(prompt) // 4))
            result["cache_miss_tokens"] = input_tokens - result.get("cache_hit_tokens", 0)
        # Calculate hit rate
        total = result["cache_hit_tokens"] + result["cache_miss_tokens"]
        result["cache_hit_rate"] = round(result["cache_hit_tokens"] / total * 100, 1) if total > 0 else 0.0
        self._emit_cache_metrics(result)
        return result

    def _emit_cache_metrics(self, result: dict) -> None:
        """Emit prefix-cache hit-rate metrics to the reference channel.

        P1-3 closure: cache hit/miss tokens + hit rate flow into the RC so
        RecordCenter stats/export cover the LLM prefix cache. Best-effort,
        never raises.
        """
        try:
            from l3.bus.reference_channel import get_rc

            get_rc().event(
                "llm_cache_metrics",
                {
                    "provider": self.config.provider,
                    "model": self.config.model,
                    "hit_tokens": result.get("cache_hit_tokens", 0),
                    "miss_tokens": result.get("cache_miss_tokens", 0),
                    "hit_rate": result.get("cache_hit_rate", 0.0),
                },
                source="llm_engine",
            )
        except Exception:
            logger.debug("llm: cache metrics RC emit skipped")

    @property
    def provider_name(self) -> str:
        """Return the current provider's name (e.g. 'openai', 'anthropic')."""
        return self.config.provider

    def embed(self, texts: list[str]) -> dict:
        """Embed texts via the active provider (graceful if unsupported).

        Delegates to ``LLMProvider.embed``; providers without embedding
        support return ``{"success": False, "error": ...}`` so callers
        (e.g. the skill retriever) degrade to lexical retrieval.
        """
        try:
            return self._provider.embed(texts)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def tool_use(
        self,
        prompt: str,
        tools: list[ToolSpec],
        system: str = "",
        max_turns: int = 5,
        user_id: str = "",
        context_trail: list[dict] | None = None,
        **overrides: Any,
    ) -> dict:
        """LLM autonomously calls tools to fulfill a task.

        Args:
            prompt: The user's task description
            tools: List of ToolDef definitions the LLM can call
            system: System prompt
            max_turns: Max tool-call iterations
            user_id: Per-agent KV cache isolation (DeepSeek) or cache_control key
            context_trail: Previous conversation turns for continuity

        Returns:
            {"content": final_response, "tool_calls": [...], "turns": N, "context_trail": [...]}
        """
        import json as _json
        import uuid

        prompt, system, cache_extra = self._get_strategy().optimize(prompt, system, user_id)

        messages = list(context_trail or [])
        if system and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # ToolSearch: defer loading — only send relevant tools (saves ~10-18% tokens)
        if self.config.tool_search and len(tools) > _TOOL_SEARCH_MIN_COUNT:
            ts = ToolSearch()
            ts.register_many(tools)
            active_tools = ts.search(prompt, max_results=_TOOL_SEARCH_MAX_RESULTS)
            logger.debug("tool_search: %d → %d tools for prompt[:LOG_TRUNC_60]", len(tools), len(active_tools))
        else:
            active_tools = tools

        tool_defs = [self._tool_def_to_api(t) for t in active_tools]
        tool_map = {t.name: t for t in tools}
        all_calls: list[dict] = []
        reasoning_trail: list[str] = []
        reasoning_tokens_total = 0
        tools_elapsed_total = 0.0
        import concurrent.futures as _cf

        for turn in range(max_turns):
            # ── Inject turn budget warning ──
            remaining = max_turns - turn
            from l1.kernel.prompts import get_prompt as _gp

            if remaining <= LOOP_TURN_WARNING_THRESHOLD and messages:
                warning = {"role": "user", "content": _gp("llm.turn_budget_warning", "").format(remaining=remaining)}
                messages.append(warning)

            # Build request with tool definitions
            merged = {**cache_extra, **overrides}
            # Apply provider capability filtering
            strategy_params = self._apply_strategy(merged)
            model_name = (
                strategy_params.get("model", self.config.model) if self.config and self.config.model else FALLBACK_MODEL
            )
            max_tok = strategy_params.get("max_tokens", self.config.max_tokens)
            temp = strategy_params.get("temperature", self.config.temperature)
            reff = strategy_params.get("reasoning_effort", "")
            tbud = strategy_params.get("thinking_budget", 0)

            body_dict: dict = {
                "model": model_name,
                "messages": messages,
                "tools": tool_defs,
                "max_tokens": max_tok,
                "temperature": temp,
            }
            if user_id:
                body_dict["user_id"] = user_id
            if self.config.cache_retention >= LLM_CACHE_RETENTION_THRESHOLD:
                body_dict["prompt_cache_retention"] = LLM_CACHE_RETENTION_STRING
            if reff and reff != "none":
                body_dict["reasoning_effort"] = reff
            if tbud > 0:
                body_dict["thinking"] = {"type": "enabled", "budget_tokens": tbud}
                body_dict["max_tokens"] = max(max_tok, tbud + LLM_THINKING_BUFFER)
            body = _json.dumps(body_dict).encode()

            try:
                response = self._call_api(body)
                content = response.get("content", "")
                tool_calls = response.get("tool_calls", [])
                reasoning = response.get("reasoning_content", "") or ""
                if reasoning:
                    reasoning_trail.append(reasoning)
                reasoning_tokens_total += response.get("reasoning_tokens", 0) or 0

                if not tool_calls:
                    # LLM finished — no more tool calls
                    return {
                        "content": content,
                        "tool_calls": all_calls,
                        "turns": turn + 1,
                        "reasoning_trail": reasoning_trail,
                        "reasoning_tokens": reasoning_tokens_total,
                        "tools_elapsed": round(tools_elapsed_total, 3),
                        "context_trail": messages[-CONTEXT_TRAIL_TRUNC:],
                    }

                # Execute tool calls in parallel with per-handler timeout
                assistant_msg = {"role": "assistant", "content": content, "tool_calls": [tc for tc in tool_calls]}
                if reasoning:
                    # DeepSeek thinking mode: requests carrying `tools` MUST
                    # echo the full reasoning_content back on every follow-up.
                    assistant_msg["reasoning_content"] = reasoning
                messages.append(assistant_msg)

                with _cf.ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
                    futures = {}
                    for tc in tool_calls:
                        fn_name = tc.get("function", {}).get("name", "")
                        fn_args = _json.loads(tc.get("function", {}).get("arguments", "{}"))
                        call_id = tc.get("id", uuid.uuid4().hex[:HASH_TRUNC_SHORT])
                        tool_def = tool_map.get(fn_name)
                        t_tool = time.time()
                        futures[
                            pool.submit(LLMEngine._execute_one_tool, tool_def, fn_args, call_id, fn_name, t_tool)
                        ] = tc

                    for future in _cf.as_completed(futures, timeout=_LLM_TOOL_TIMEOUT * 2):
                        tc = futures[future]
                        try:
                            call_record = future.result()
                        except _cf.TimeoutError:
                            call_record = {
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": {},
                                "error": "timeout",
                                "call_id": tc.get("id", uuid.uuid4().hex[:HASH_TRUNC_SHORT]),
                                "elapsed": _LLM_TOOL_TIMEOUT,
                            }
                        except Exception as e:
                            call_record = {
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": {},
                                "error": str(e),
                                "call_id": tc.get("id", uuid.uuid4().hex[:HASH_TRUNC_SHORT]),
                                "elapsed": 0.0,
                            }
                        all_calls.append(call_record)
                        tools_elapsed_total += float(call_record.get("elapsed", 0) or 0)
                        result_str = _json.dumps(
                            call_record.get("result", call_record.get("error", "")),
                            ensure_ascii=False,
                        )[:LLM_TOOL_RESULT_TRUNCATION]
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_record["call_id"],
                                "content": result_str,
                            }
                        )

            except Exception as e:
                return {
                    "content": "",
                    "tool_calls": all_calls,
                    "turns": turn + 1,
                    "reasoning_trail": reasoning_trail,
                    "reasoning_tokens": reasoning_tokens_total,
                    "tools_elapsed": round(tools_elapsed_total, 3),
                    "error": str(e),
                    "context_trail": messages[-CONTEXT_TRAIL_TRUNC:],
                }

        return {
            "content": "Max turns reached",
            "tool_calls": all_calls,
            "turns": max_turns,
            "reasoning_trail": reasoning_trail,
            "reasoning_tokens": reasoning_tokens_total,
            "tools_elapsed": round(tools_elapsed_total, 3),
            "context_trail": messages[-CONTEXT_TRAIL_TRUNC:],
        }


# ── LLMPort adapter (breaks L3→L4 dependency) ──


def _register_llm_port(engine: LLMEngine) -> None:
    """Wrap LLMEngine as an LLMPort and register it in the kernel port registry.

    Registered as "llm" so L3 callers can use ``get_port("llm")`` instead of
    importing from ``l4.llm.llm`` directly.
    """
    from l1.kernel.ports import register_port
    from l4.ports import LLMPort

    class _LLMEngineAdapter(LLMPort):
        """Thin adapter: LLMEngine → LLMPort interface."""

        def tool_use(
            self,
            prompt: str,
            tools: list,
            system: str = "",
            max_turns: int = 10,
            user_id: str = "",
            **model_kwargs: Any,
        ) -> dict:
            """Run a tool-using turn loop via the engine."""
            return engine.tool_use(prompt, tools, system=system, max_turns=max_turns, user_id=user_id, **model_kwargs)

        def generate(self, prompt: str, system: str = "", user_id: str = "", **model_kwargs: Any) -> dict:
            """Generate a completion via the engine."""
            return engine.generate(prompt, system=system, user_id=user_id, **model_kwargs)

        def context_window(self, cell_id: str = "", agent_id: str = "") -> dict:
            """Return the engine's context window usage for the given scope."""
            cw = engine.context_window(cell_id=cell_id, agent_id=agent_id)
            return {"context_window": cw, "source": "llm"}

        def optimize_prompt(self, prompt: str, system: str = "") -> tuple[str, str]:
            """Return the optimized prompt and system pair."""
            return optimize_prompt(prompt, system)

        def provider_status(self) -> dict:
            """Report the active provider health status."""
            return {"status": "ok", "provider": engine.provider_name}

    register_port("llm", _LLMEngineAdapter())


def resolve_protocol(configured: str, supports_stateful: bool) -> str:
    """Resolve a wire protocol from a configured value + provider capability.

    Pure logic — TS-equivalent portable: same inputs yield the same output
    with no I/O or module state. ``auto`` prefers stateful when the provider
    implements message-list generation (``generate_with_messages``);
    anything else degrades to stateless. Unknown configured values fall
    back to stateless (fail-closed).
    """
    mode = str(configured or "").strip().lower()
    if mode == "auto":
        return "stateful" if supports_stateful else "stateless"
    return mode if mode in ("stateless", "stateful") else "stateless"


def optimize_prompt(prompt: str, system: str = "") -> tuple[str, str]:
    """Optimize prompt structure for token efficiency and cache matching.

    Based on Copilot's Treatment B approach:
    - Structured [System]/[Task]/[Context] sections for cache prefix alignment
    - Minimized redundant whitespace
    - Clear section boundaries for cache_control breakpoint matching
    """
    sections = []
    if system:
        sections.append(f"[System]\n{system.strip()}")
    sections.append(f"[Task]\n{prompt.strip()}")
    optimized = "\n\n".join(sections)
    return optimized, system
