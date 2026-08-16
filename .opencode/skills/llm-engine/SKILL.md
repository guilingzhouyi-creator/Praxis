---
name: llm-engine
description: Use when writing or modifying Praxis LLM/reasoning code — llm_providers, LLMEngine, provider failover (llm_retry), effort tiers, strategy packs, model_spec cascade, http_pool keep-alive, or llm_tools/hooks integration.
---

## Overview

Architecture guide for the L4 LLM/reasoning system (`src/l4/llm/`). Config-first: no model name is hardcoded in agent code — everything flows through providers, effort tiers, strategy packs, and the model_spec cascade.

## Module Map

- **Providers**: `llm_providers.py` — unified `LLMProvider` ABC (OpenAI/Anthropic/DeepSeek/Ollama/mock), streaming + tool calls
- **Engine**: `llm.py` — `LLMEngine`: strategy application, effort normalization, capability probes, `generate`/`tool_use`/`context_window`; `llm_engine.py`, `llm_base.py`
- **Failover**: `llm_retry.py` — provider failover after consecutive failures (see conventions)
- **Transport**: `http_pool.py` — per-thread keep-alive `HTTPConnection` reuse (no fresh TLS handshake per call); `Retry-After` honored
- **Extras**: `llm_tools.py` (tool-call marshalling), `llm_hooks.py` (inference hooks)
- **Port**: `"llm"` — AgentLoop resolves the engine via `get_port("llm")` (duck-typed, wired at boot)

## Core Conventions

- **Provider failover** (`llm_retry.py`): after `LLM_FAILOVER_THRESHOLD` (3) consecutive failures on the primary provider, the next call rebuilds the provider from `ModelRegistry.get_fallback` — SAME model-spec semantics (spec keeps role/executor; only provider/endpoint/credential swap) — and replays the request once. Success resets the counter; `LLM_FAILOVER_COOLDOWN` (300s) window since the last switch prevents thrashing. Switch recorded via `logger.warning`; `get_fallback` requires another discovered provider with a valid key and skips the current one. Params `LLM_FAILOVER_*` (params/api.py), master switch `LLM_FAILOVER_ENABLED` (default on); no fallback keeps the primary and returns the error payload.
- **Effort tiers (provider-normalized)**: requested `reasoning_effort` clamped per provider by `EFFORT_TIERS_BY_PROVIDER` (params/api.py) — a tier outside the provider's set falls back to the highest supported at or below the request; empty set = no effort support (param dropped). `EFFORT_RANK` orders none < low < medium < high < xhigh < max. `think.max_reasoning` (default "max") caps the ceiling; `think.max_budget` caps budget tokens.
- **Strategy packs**: `config/praxis.yaml` `model_spec.strategies` — named presets (fast/balanced/deep/xhigh/max) combining reasoning_effort, thinking_budget, max_tokens, temperature. Applied via `ModelService.resolve_dict_with_strategy(spec_name, strategy)`.
- **Model spec cascade**: per-call overrides > `model_spec.<executor>` > llm global (praxis.yaml); executors: scout / l3a / l3a_subagent / subagent / r4_agent. `ModelService.resolve(spec_name, ...)` merges the chain (deep-merge + env interpolation + credential resolution); `_clamp_reasoning` enforces ceilings.
- **Credential hygiene**: provider creds live in the vault, never in code; API keys never logged or exposed in responses (see security-reviewer skill).
- **API surface**: `/api/v2/providers*` (list/register/remove/health/config), `/api/v2/model-spec*` (view/update per executor + strategies).
- **Think registry** (L3): `scheduler/think_registry.py` — 3-layer thinking-config overrides (Global/Cell/Agent): inherit / auto_balance / manual.

## Tests

- `python -m pytest tests/ -k "llm or provider or model" -x -q`
- Endpoint manifest: `python -m l4.api.api_endpoints` before pushing API changes
