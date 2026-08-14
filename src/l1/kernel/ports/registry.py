"""Port adapter registry — register/get/reset adapters wired at boot."""

from __future__ import annotations

_PORTS: dict[str, object] = {}


def register_port(name: str, adapter: object) -> None:
    """Register a port adapter at boot time."""
    _PORTS[name] = adapter


def get_port(name: str) -> object:
    """Retrieve a registered port adapter by name. Raises KeyError if not registered."""
    if name not in _PORTS:
        raise KeyError(f"port '{name}' not registered — call register_port() first")
    return _PORTS[name]


def reset_ports() -> None:
    """Clear port registry (for testing / hot-reload)."""
    _PORTS.clear()
