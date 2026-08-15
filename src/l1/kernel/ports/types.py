"""Port types — shared value types used across port interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Endpoint:
    """Transport endpoint — abstract address, not tied to TCP (host, port)."""

    address: str = ""
    hint: str = "tcp"


@dataclass
class Result:
    """Generic success/failure result — no exception leak across port boundaries."""

    success: bool = True
    error: str = ""
    data: dict = field(default_factory=dict)

    @staticmethod
    def ok(**data: Any) -> Result:
        """Build a success Result carrying optional *data*."""
        return Result(success=True, data=data)

    @staticmethod
    def fail(msg: str, **data: Any) -> Result:
        """Build a failure Result with *msg* and optional *data*."""
        return Result(success=False, error=msg, data=data)


@dataclass
class Message:
    """Domain message — locale-aware, adapter-neutral serialization."""

    type: str = "message"
    source: str = ""
    target: str = ""
    payload: Any = None
    timestamp: float = 0.0
    locale: str = "en"
    headers: dict = field(default_factory=dict)


@dataclass
class Event:
    """Domain event — carry pre-localized message for multi-lingual consumers."""

    type: str = ""
    source: str = ""
    severity: str = "info"
    message: str = ""
    message_locale: str = ""
    data: dict = field(default_factory=dict)
