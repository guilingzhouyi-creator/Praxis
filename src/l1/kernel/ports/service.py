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


# ── CardRegistryPort ──


class CardRegistryPort(ABC):
    """Card type registry — query and install card definitions."""

    @abstractmethod
    def list_types(self) -> list[dict]:
        """List registered card type definitions."""

    @abstractmethod
    def install_def(self, cdef: dict, source: str = "") -> bool:
        """Install a card type definition; return success."""


# ── MonitorBusPort ──


class MonitorBusPort(ABC):
    """Monitoring event bus — structured event emission and query."""

    @abstractmethod
    def emit(self, type_: str, source: str, severity: str, message: str, data: dict | None = None) -> None:
        """Emit a structured monitoring event."""

    @abstractmethod
    def query(
        self, type_prefix: str = "", severity: str = "", source: str = "", since: float = 0.0, limit: int = 100
    ) -> list[dict]:
        """Query recent monitoring events matching the filters."""


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


# ── Auth Port ──


class AuthPort(ABC):
    """Auth — token issuance, verification, revocation and refresh."""

    @abstractmethod
    def issue_token(self, identity: str, ttl: float = AUTH_TOKEN_TTL_SECONDS) -> dict:
        """Issue a token for *identity* with the given TTL; return the token dict."""

    @abstractmethod
    def verify_token(self, token: str) -> dict:
        """Verify *token*; return identity/validity details."""

    @abstractmethod
    def revoke_token(self, token: str) -> dict:
        """Revoke *token*; return the revocation result."""

    @abstractmethod
    def refresh_token(self, token: str) -> dict:
        """Refresh *token*; return the new token dict."""


# ── WebSocket Port ──


class WebSocketPort(ABC):
    """WebSocket — bidirectional client channels for realtime frontend interaction."""

    @abstractmethod
    def upgrade(self, request: Any) -> Any:
        """Upgrade an HTTP request to a WebSocket connection handle."""

    @abstractmethod
    def recv(self, conn: Any) -> dict | None:
        """Receive the next message dict from *conn*; None when closed."""

    @abstractmethod
    def send(self, conn: Any, msg: dict) -> bool:
        """Send *msg* over *conn*; return success."""

    @abstractmethod
    def close(self, conn: Any) -> None:
        """Close a WebSocket connection."""

    @abstractmethod
    def broadcast(self, event: str, data: dict) -> None:
        """Broadcast *event* with *data* to all connected clients."""


# ── RPC Server Port ──


class RpcServerPort(ABC):
    """RPC server — remote method invocation for distributed cells/nodes."""

    @abstractmethod
    def register_handler(self, method: str, handler: Callable) -> None:
        """Register a handler for an RPC *method*."""

    @abstractmethod
    def call(self, method: str, params: dict | None = None) -> dict:
        """Invoke an RPC *method* with *params*; return the result dict."""

    @abstractmethod
    def notify(self, method: str, params: dict | None = None) -> None:
        """Fire an RPC notification (no response expected)."""


# ── Filesystem Port ──


class FilesystemPort(ABC):
    """Filesystem — file read/write, tree listing and change watching."""

    @abstractmethod
    def read(self, path: str) -> dict:
        """Read a file; return content in the result dict."""

    @abstractmethod
    def write(self, path: str, content: str) -> dict:
        """Write *content* to a file; return the result dict."""

    @abstractmethod
    def list_tree(self, root: str) -> dict:
        """List the file tree under *root*; return entries in the result dict."""

    @abstractmethod
    def watch(self, root: str, callback: Callable) -> dict:
        """Watch *root* for changes, invoking *callback*; return the watch handle."""
