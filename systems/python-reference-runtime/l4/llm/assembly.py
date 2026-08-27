"""Provider message assembly — pluggable factory + protocol selection (3.1 G1/G2).

The stateless Chat path builds a provider wire payload from (prompt, system).
Providers may register a default assembler reproducing the historical
hardcoded splicing; plugins override via register_assembler (the reserved
plugin-marketplace assembly factory — nothing is hardcoded). A per-provider
protocol (stateless | stateful | auto) drives which wire path the engine
takes; the config-file default comes from cache_strategy (llm.cache).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_assemblers: dict[str, Callable[..., list[dict]]] = {}
_protocols: dict[str, str] = {}


def register_assembler(provider: str, fn: Callable[..., list[dict]]) -> None:
    """Register a custom stateless message assembler for a provider."""
    _assemblers[provider.strip().lower()] = fn


def get_assembler(provider: str) -> Callable[..., list[dict]]:
    """Return the provider's assembler (generic OpenAI-compatible default)."""
    return _assemblers.get(provider.strip().lower(), _default_assembler)


def set_protocol(provider: str, protocol: str) -> None:
    """Set the wire protocol for a provider (stateless | stateful | auto)."""
    p = protocol.strip().lower()
    if p in ("stateless", "stateful", "auto"):
        _protocols[provider.strip().lower()] = p


def get_protocol(provider: str, default: str | None = None) -> str | None:
    """Return the configured protocol for a provider (None when unset)."""
    return _protocols.get(provider.strip().lower(), default)


def _default_assembler(prompt: str, system: str = "", **kwargs: Any) -> list[dict]:
    """Generic OpenAI-compatible assembler: [system, user]."""
    fallback = kwargs.pop("fallback_system", "You are a helpful assistant.")
    return [
        {"role": "system", "content": system or fallback},
        {"role": "user", "content": prompt},
    ]


def assemble_messages(provider: str, prompt: str, system: str = "", **kwargs: Any) -> list[dict]:
    """Build the stateless message list for a provider via its assembler."""
    return list(get_assembler(provider)(prompt, system, **kwargs))


def reset_assembly() -> None:
    """Reset the assembly registry (tests / lifecycle)."""
    _assemblers.clear()
    _protocols.clear()
