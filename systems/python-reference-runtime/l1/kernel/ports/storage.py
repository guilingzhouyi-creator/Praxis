"""Storage port abstraction — read/write surface decoupled from the FS.

TS-friendly (P2-⑤): the storage surface is an interface (``StoragePort``)
with a synchronous filesystem adapter (``FsStoragePort``); a future TS
rewrite maps the same interface onto async I/O without touching callers.
The active adapter is obtainable via ``get_storage()``.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path


class StoragePort(ABC):
    """Text-file storage surface (read/write/exists/list)."""

    name: str = "abstract.storage"

    @abstractmethod
    def read_text(self, path: str) -> str:
        """Read a UTF-8 text file ("" on missing file)."""

    @abstractmethod
    def write_text(self, path: str, text: str) -> None:
        """Write UTF-8 text (creates parent dirs)."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Whether the path exists."""

    @abstractmethod
    def list_json(self, glob: str) -> list[str]:
        """List JSON file paths under a glob pattern (sorted)."""


class FsStoragePort(StoragePort):
    """Filesystem adapter — synchronous, used by the current runtime."""

    name: str = "fs.storage"

    def read_text(self, path: str) -> str:
        """Read a UTF-8 text file ("" on missing file)."""
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return ""

    def write_text(self, path: str, text: str) -> None:
        """Write UTF-8 text (creates parent dirs)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def exists(self, path: str) -> bool:
        """Whether the path exists."""
        return Path(path).exists()

    def list_json(self, glob: str) -> list[str]:
        """List JSON file paths under a glob pattern (sorted)."""
        p = Path(glob)
        base = p.parent
        try:
            if not base.exists():
                return []
            return sorted(str(f) for f in base.glob(p.name) if f.is_file())
        except OSError:
            return []


_storage_lock = threading.Lock()
_storage: StoragePort | None = None


def get_storage() -> StoragePort:
    """Get the active storage adapter (default: filesystem)."""
    global _storage
    with _storage_lock:
        if _storage is None:
            _storage = FsStoragePort()
        return _storage


def set_storage(port: StoragePort) -> None:
    """Replace the storage adapter (tests / alternate backends)."""
    global _storage
    with _storage_lock:
        _storage = port


def reset_storage() -> None:
    """Reset to the default filesystem adapter."""
    global _storage
    with _storage_lock:
        _storage = None
