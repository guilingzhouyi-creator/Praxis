"""Service port abstractions — auth, WebSocket, RPC, filesystem, input activity.

Domain ports (I18n / CardRegistry / MonitorBus / CandidateLedger / LLM) moved
to l3.ports / l4.ports (WS5.1) so the kernel namespace only carries mechanism
ports; this module keeps the kernel-local service ports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from l1.kernel.params.api import AUTH_TOKEN_TTL_SECONDS
from l1.kernel.ports.types import InputActivitySnapshot


class InputActivityPort(ABC):
    """Platform-neutral aggregate input activity provider."""

    @abstractmethod
    def start(self) -> bool:
        """Start activity observation without collecting input contents."""

    @abstractmethod
    def stop(self) -> None:
        """Stop activity observation and release platform resources."""

    @abstractmethod
    def snapshot(self) -> InputActivitySnapshot:
        """Return the latest privacy-preserving activity aggregate."""


# ── Auth Port ──


class AuthPort(ABC):
    """Auth — token issuance, verification, revocation and refresh."""

    @abstractmethod
    def issue_token(self, identity: str, ttl: float = AUTH_TOKEN_TTL_SECONDS) -> dict:
        """Issue a token for *identity*; return the token record."""

    @abstractmethod
    def verify_token(self, token: str) -> dict:
        """Verify *token*; return the identity or an error."""

    @abstractmethod
    def revoke_token(self, token: str) -> bool:
        """Revoke *token*; return success."""

    @abstractmethod
    def refresh_token(self, token: str) -> dict:
        """Refresh *token*; return a new token record."""


# ── WebSocket Port ──


class WebSocketPort(ABC):
    """WebSocket — connection upgrade, messaging and broadcast."""

    @abstractmethod
    def upgrade(self, request: Any) -> dict:
        """Upgrade an HTTP request to a WebSocket connection."""

    @abstractmethod
    def recv(self, conn: Any) -> dict:
        """Receive one message from *conn*."""

    @abstractmethod
    def send(self, conn: Any, msg: dict) -> bool:
        """Send one message to *conn*."""

    @abstractmethod
    def close(self, conn: Any) -> None:
        """Close *conn*."""

    @abstractmethod
    def broadcast(self, event: str, data: dict) -> None:
        """Broadcast an event to all connections."""


# ── RPC Server Port ──


class RpcServerPort(ABC):
    """RPC server — method registration, calls and notifications."""

    @abstractmethod
    def register_handler(self, method: str, handler: Callable) -> None:
        """Register *handler* for *method*."""

    @abstractmethod
    def call(self, method: str, params: dict | None = None) -> dict:
        """Invoke *method* with *params*; return the result dict."""

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
