"""LLMRetryMixin — low-level API call with layered retry policy.

Extracted from ``llm.py`` (LLMEngine).  Owns ``_call_api``: the HTTP POST
with persistent-connection pool, provider header/URL adaptation, and the
four retry layers (overflow compact / transient backoff / empty response /
rate limit).  The concrete ``LLMEngine`` composes it with the tools mixin
and the engine core.
"""

from __future__ import annotations

import http.client
import json
import logging
from typing import TYPE_CHECKING

from l1.kernel.params.api import (
    LLM_EMPTY_RESPONSE_WAITS,
    LLM_HTTP_TIMEOUT,
    LLM_MAX_EMPTY_RETRIES,
    LLM_MAX_OVERFLOW_RETRIES,
    LLM_MAX_RATE_LIMIT_RETRIES,
    LLM_MAX_TRANSIENT_RETRIES,
    LLM_RATE_LIMIT_WAIT,
    LLM_TRANSIENT_BACKOFF_BASE,
)
from l1.kernel.params.system import LOG_TRUNC_60, LOG_TRUNC_200

from .http_pool import http_post

if TYPE_CHECKING:
    from .llm_base import LLMConfig, LLMProvider

logger = logging.getLogger(__name__)


class LLMRetryMixin:
    """LLMRetryMixin — HTTP API call with layered retry + provider adaptation."""

    # ── Attributes injected by the concrete LLMEngine (see llm.py) ──
    config: LLMConfig
    _provider: LLMProvider

    def _call_api(self, body: bytes, retry_count: int = 0) -> dict:
        """Low-level API call with retry layers. Returns parsed response dict with cache stats.

        Retry layers (AtomCode-style):
          1. Overflow (context too long) → compact + retry (3 attempts)
          2. Transient (5xx/timeout) → linear backoff 3/6/9s (3 attempts)
          3. Empty response (200 with no content) → retry 1/1/2/2/3s (5 attempts)
          4. Rate limit (429) → wait from Retry-After header or 60s (5 attempts)
        """
        import time as _time

        provider_name = self.config.provider
        if provider_name == "mock":
            return self._mock_response(body)

        provider = self._provider
        headers = {"Content-Type": "application/json"}
        try:
            gh = getattr(provider, "get_headers", None)
            if gh:
                headers.update(gh())
        except Exception as e:
            logger.warning("provider get_headers failed: %s", e)
        gu = getattr(provider, "get_api_url", None)
        url = gu(self.config.api_url) if gu else self.config.api_url

        # Persistent connection reuse (per-thread) instead of a fresh
        # TCP/TLS handshake on every call.
        try:
            code, raw, resp_headers = http_post(url, body, headers, LLM_HTTP_TIMEOUT)
        except (OSError, TimeoutError, http.client.HTTPException) as e:
            return self._transient_retry(body, retry_count, str(e), _time)
        if code >= 400:
            return self._http_error_retry(body, retry_count, code, raw, resp_headers, _time)
        return self._success_response(body, retry_count, raw, provider_name, _time)

    def _mock_response(self, body: bytes) -> dict:
        """Build the mock provider response from the request body."""
        data = json.loads(body)
        prompt = data["messages"][-1]["content"]
        return {
            "content": f"[mock] tool_use: {prompt[:LOG_TRUNC_60]}...",
            "tool_calls": [],
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
        }

    def _error_payload(self, err: str) -> dict:
        """Build an empty tool response that carries a provider error string."""
        return {
            "content": "",
            "tool_calls": [],
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "error": err,
        }

    def _transient_retry(self, body: bytes, retry_count: int, err: str, _time) -> dict:
        """Retry transient transport errors with linear backoff, else return an error payload."""
        if (
            any(x in err for x in ("timeout", "reset", "refused", "timed out", "BadStatusLine"))
            and retry_count < LLM_MAX_TRANSIENT_RETRIES
        ):
            wait = LLM_TRANSIENT_BACKOFF_BASE * (retry_count + 1)
            _time.sleep(wait)
            return self._call_api(body, retry_count + 1)
        return self._error_payload(err)

    def _http_error_retry(
        self, body: bytes, retry_count: int, code: int, raw: bytes, resp_headers: dict, _time
    ) -> dict:
        """Handle a non-2xx HTTP status — rate-limit and overflow retries, else an error payload."""
        body_text = raw.decode(errors="replace")[:LOG_TRUNC_200]
        if code == 429 and retry_count < LLM_MAX_RATE_LIMIT_RETRIES:
            wait = LLM_RATE_LIMIT_WAIT
            ra = resp_headers.get("retry-after", "")
            if ra and ra.isdigit():
                wait = int(ra)
            _time.sleep(wait)
            return self._call_api(body, retry_count + 1)
        if code in (413, 400) and "too long" in body_text.lower() and retry_count < LLM_MAX_OVERFLOW_RETRIES:
            logger.warning("llm overflow, compact+retry (attempt %d/%d)", retry_count + 1, LLM_MAX_OVERFLOW_RETRIES)
            try:
                from .memory.memory import get_memory

                get_memory().compact("system")
            except Exception:
                logger.debug("llm: memory compact failed")
            return self._call_api(body, retry_count + 1)
        return self._error_payload(f"HTTP {code}: {body_text}")

    def _success_response(self, body: bytes, retry_count: int, raw: bytes, provider_name: str, _time) -> dict:
        """Parse a 2xx body, retry empty responses, and build the provider-specific result."""
        try:
            data = json.loads(raw)
        except Exception:
            return self._error_payload(f"json decode: {raw[:LOG_TRUNC_200].decode(errors='replace')}")

        # Empty response detection
        content = ""
        tool_calls = []
        reasoning_content = ""
        if isinstance(data, dict):
            msg = data.get("choices", [{}])[0].get("message", {}) if "choices" in data else {}
            content = msg.get("content", "") or data.get("content", "")
            tool_calls = msg.get("tool_calls", []) or data.get("tool_calls", [])
            reasoning_content = msg.get("reasoning_content", "") or data.get("reasoning_content", "")
        if not content and not tool_calls and retry_count < LLM_MAX_EMPTY_RETRIES:
            wait = LLM_EMPTY_RESPONSE_WAITS[retry_count]
            _time.sleep(wait)
            return self._call_api(body, retry_count + 1)

        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        cache_hit = usage.get("prompt_cache_hit_tokens", usage.get("cache_hit", 0))
        cache_miss = usage.get(
            "prompt_cache_miss_tokens",
            usage.get(
                "cache_miss",
                usage.get("prompt_tokens", 0)
                - (usage.get("prompt_cache_hit_tokens", 0) if "prompt_tokens" in usage else 0),
            ),
        )
        reasoning_tokens = (usage.get("output_tokens_details", {}) or {}).get("reasoning_tokens", 0)

        if provider_name in ("ollama",):
            msg = data.get("message", {})
            return {
                "content": msg.get("content", ""),
                "tool_calls": msg.get("tool_calls", []),
                "reasoning_content": msg.get("reasoning_content", ""),
                "reasoning_tokens": reasoning_tokens,
                "cache_hit_tokens": cache_hit,
                "cache_miss_tokens": cache_miss,
            }

        if provider_name in ("openai",):
            choice = data["choices"][0]["message"]
            return {
                "content": choice.get("content", ""),
                "tool_calls": choice.get("tool_calls", []),
                "reasoning_content": choice.get("reasoning_content", ""),
                "reasoning_tokens": reasoning_tokens,
                "cache_hit_tokens": cache_hit,
                "cache_miss_tokens": cache_miss,
            }

        return {
            "content": "",
            "tool_calls": [],
            "reasoning_content": reasoning_content,
            "reasoning_tokens": reasoning_tokens,
            "cache_hit_tokens": cache_hit,
            "cache_miss_tokens": cache_miss,
        }
