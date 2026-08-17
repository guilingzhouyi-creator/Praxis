"""L4 domain ports — I18nPort / LLMConfig / LLMPort.

WS5.1 surface shrink: domain ports moved OUT of the kernel namespace so
the Rust kernel boundary only carries mechanism ports. Importers use
``from l4.ports import ...``; the kernel port registry name is unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from l1.kernel.params.agent import LLM_CACHE_RETENTION_THRESHOLD
from l1.kernel.params.api import (
    LLM_DEFAULT_CACHE_BREAKPOINTS,
    LLM_DEFAULT_MAX_TOKENS,
    LLM_DEFAULT_TEMPERATURE,
)

# ── I18n Port ──


class I18nPort(ABC):
    """Internationalization port — key-based translation lookup."""

    @abstractmethod
    def t(self, key: str, **kwargs: Any) -> str:
        """Translate *key* in the active locale, formatting with *kwargs*."""

    def t_locale(self, locale: str, key: str, **kwargs: Any) -> str:
        """Translate *key* in an explicit *locale* without switching the active one."""
        current = self.get_locale()
        result: str = key
        try:
            self.set_locale(locale)
            result = self.t(key, **kwargs)
        finally:
            self.set_locale(current)
        return result

    @abstractmethod
    def set_locale(self, locale: str) -> None:
        """Switch the active locale."""

    @abstractmethod
    def get_locale(self) -> str:
        """Return the active locale code."""

    @abstractmethod
    def get_available(self) -> list[str]:
        """Return the list of available locale codes."""

    @abstractmethod
    def register(self, locale: str, data: dict[str, str | dict]) -> None:
        """Register translation data for *locale*."""

    @abstractmethod
    def register_file(self, locale: str, path: str) -> bool:
        """Load translation data for *locale* from *path*; return success."""


# ── LLM Config + Port ──


@dataclass
class LLMConfig:
    """LLM engine configuration — provider, model, parameters."""

    provider: str = "mock"
    model: str = ""
    max_tokens: int = LLM_DEFAULT_MAX_TOKENS
    temperature: float = LLM_DEFAULT_TEMPERATURE
    api_key: str = ""
    api_url: str = ""
    device_name: str = "llm"
    cache_breakpoints: int = LLM_DEFAULT_CACHE_BREAKPOINTS
    cache_retention: float = LLM_CACHE_RETENTION_THRESHOLD
    tool_search: bool = False
    use_websocket: bool = False
    reasoning_effort: str = "none"
    thinking_budget: int = 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LLMConfig):
            return False
        return self.provider == other.provider and self.model == other.model and self.api_url == other.api_url


class LLMPort(ABC):
    """Abstract port for LLM operations — generate, tool_use, context management."""

    @abstractmethod
    def tool_use(
        self, prompt: str, tools: list, system: str = "", max_turns: int = 10, user_id: str = "", **model_kwargs: Any
    ) -> dict:
        """Run a multi-turn tool-use loop; return the result dict."""

    @abstractmethod
    def generate(self, prompt: str, system: str = "", user_id: str = "", **model_kwargs: Any) -> dict:
        """Generate a completion for *prompt*; return the result dict."""

    @abstractmethod
    def context_window(self, cell_id: str = "", agent_id: str = "") -> dict:
        """Return context-window usage statistics for a cell/agent."""

    @abstractmethod
    def optimize_prompt(self, prompt: str, system: str = "") -> tuple[str, str]:
        """Return an optimized (prompt, system) pair."""

    @abstractmethod
    def provider_status(self) -> dict:
        """Return LLM provider status (health, model, latency)."""
