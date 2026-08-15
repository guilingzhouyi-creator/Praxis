"""Service port abstractions — LLM, auth, filesystem, WebSocket, RPC, i18n, etc."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from l1.kernel.params.agent import LLM_CACHE_RETENTION_THRESHOLD
from l1.kernel.params.api import (
    AUTH_TOKEN_TTL_SECONDS,
    LLM_DEFAULT_CACHE_BREAKPOINTS,
    LLM_DEFAULT_MAX_TOKENS,
    LLM_DEFAULT_TEMPERATURE,
)

# ── I18nPort ──


class I18nPort(ABC):
    """Internationalization port — key-based translation lookup."""

    @abstractmethod
    def t(self, key: str, **kwargs: Any) -> str: ...
    def t_locale(self, locale: str, key: str, **kwargs: Any) -> str:
        current = self.get_locale()
        result: str = key
        try:
            self.set_locale(locale)
            result = self.t(key, **kwargs)
        finally:
            self.set_locale(current)
        return result

    @abstractmethod
    def set_locale(self, locale: str) -> None: ...
    @abstractmethod
    def get_locale(self) -> str: ...
    @abstractmethod
    def get_available(self) -> list[str]: ...
    @abstractmethod
    def register(self, locale: str, data: dict[str, str | dict]) -> None: ...
    @abstractmethod
    def register_file(self, locale: str, path: str) -> bool: ...


# ── CardRegistryPort ──


class CardRegistryPort(ABC):
    """Card type registry — query and install card definitions."""

    @abstractmethod
    def list_types(self) -> list[dict]: ...
    @abstractmethod
    def install_def(self, cdef: dict, source: str = "") -> bool: ...


# ── MonitorBusPort ──


class MonitorBusPort(ABC):
    """Monitoring event bus — structured event emission and query."""

    @abstractmethod
    def emit(self, type_: str, source: str, severity: str, message: str, data: dict | None = None) -> None: ...
    @abstractmethod
    def query(
        self, type_prefix: str = "", severity: str = "", source: str = "", since: float = 0.0, limit: int = 100
    ) -> list[dict]: ...


# ── R4 Candidate Ledger Port ──


class CandidateLedgerPort(ABC):
    """R4 evidence-candidate lifecycle exposed to shell and API adapters."""

    @abstractmethod
    def list_candidates(self, state: str = "") -> list[dict]: ...

    @abstractmethod
    def get_candidate(self, candidate_id: str) -> dict | None: ...

    @abstractmethod
    def status(self) -> dict: ...

    @abstractmethod
    def set_enabled(self, enabled: bool) -> dict: ...

    @abstractmethod
    def validate(self, candidate_id: str) -> dict: ...

    @abstractmethod
    def publish(self, candidate_id: str, intent: str, scope: str = "") -> dict: ...

    @abstractmethod
    def activate(self, candidate_id: str) -> dict: ...

    @abstractmethod
    def retire(self, candidate_id: str) -> dict: ...


# ── LLM Port ──


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
    ) -> dict: ...
    @abstractmethod
    def generate(self, prompt: str, system: str = "", user_id: str = "", **model_kwargs: Any) -> dict: ...
    @abstractmethod
    def context_window(self, cell_id: str = "", agent_id: str = "") -> dict: ...
    @abstractmethod
    def optimize_prompt(self, prompt: str, system: str = "") -> tuple[str, str]: ...
    @abstractmethod
    def provider_status(self) -> dict: ...


# ── Auth Port ──


class AuthPort(ABC):
    """Auth — token issuance, verification, revocation and refresh."""

    @abstractmethod
    def issue_token(self, identity: str, ttl: float = AUTH_TOKEN_TTL_SECONDS) -> dict: ...
    @abstractmethod
    def verify_token(self, token: str) -> dict: ...
    @abstractmethod
    def revoke_token(self, token: str) -> dict: ...
    @abstractmethod
    def refresh_token(self, token: str) -> dict: ...


# ── WebSocket Port ──


class WebSocketPort(ABC):
    """WebSocket — bidirectional client channels for realtime frontend interaction."""

    @abstractmethod
    def upgrade(self, request: Any) -> Any: ...
    @abstractmethod
    def recv(self, conn: Any) -> dict | None: ...
    @abstractmethod
    def send(self, conn: Any, msg: dict) -> bool: ...
    @abstractmethod
    def close(self, conn: Any) -> None: ...
    @abstractmethod
    def broadcast(self, event: str, data: dict) -> None: ...


# ── RPC Server Port ──


class RpcServerPort(ABC):
    """RPC server — remote method invocation for distributed cells/nodes."""

    @abstractmethod
    def register_handler(self, method: str, handler: Callable) -> None: ...
    @abstractmethod
    def call(self, method: str, params: dict | None = None) -> dict: ...
    @abstractmethod
    def notify(self, method: str, params: dict | None = None) -> None: ...


# ── Filesystem Port ──


class FilesystemPort(ABC):
    """Filesystem — file read/write, tree listing and change watching."""

    @abstractmethod
    def read(self, path: str) -> dict: ...
    @abstractmethod
    def write(self, path: str, content: str) -> dict: ...
    @abstractmethod
    def list_tree(self, root: str) -> dict: ...
    @abstractmethod
    def watch(self, root: str, callback: Callable) -> dict: ...
