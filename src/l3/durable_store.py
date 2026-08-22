"""DurableJsonStore — crash-safe atomic JSON persistence (3.3, P0.4).

Envelope format (schema-versioned via ``l1.kernel.versioning``):

    {"v": <schema>, "kind": <kind>, "checksum": sha256(payload-canonical),
     "payload": {...}}

Guarantees (agent-os-3x-closure P0.4 contract):
  - **atomic replace** — payload is written to a temp file in the target
    directory, fsynced, then ``os.replace``d into place;
  - **write-ahead journal** (``<path>.journal``) — the intended record is
    journaled and fsynced BEFORE the replace; on load, a corrupt or
    truncated main file is recovered from the journal's last good record
    (and the main file self-heals from it);
  - **exclusive advisory lock** (``<path>.lock``, flock LOCK_EX|LOCK_NB) —
    a store locked by another writer fails closed instead of interleaving;
  - **idempotent writes** — an unchanged canonical payload is a no-op;
  - **corruption fail-closed** — damage beyond journal recovery raises
    :class:`DurableStoreError`; records are never silently dropped.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from l1.kernel.params.system import (
    DURABLE_JOURNAL_SUFFIX,
    DURABLE_JSON_SCHEMA_VERSION,
    DURABLE_LOCK_SUFFIX,
)
from l1.kernel.versioning import check_and_migrate

logger = logging.getLogger(__name__)

try:  # POSIX advisory locking; degraded (no cross-process lock) elsewhere.
    import fcntl as _fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover — non-POSIX dev hosts only
    _fcntl = None  # type: ignore[assignment]
    _HAVE_FCNTL = False


class DurableStoreError(RuntimeError):
    """Raised when a store is unreadable beyond journal recovery."""


def _canonical(payload) -> str:
    """Return the deterministic JSON form used for checksums/compares."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _checksum(canonical: str) -> str:
    """Return the sha256 hex digest of the canonical payload text."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DurableJsonStore:
    """Atomic, journaled, checksummed JSON map at a fixed path."""

    _path_locks: dict[str, threading.Lock] = {}
    _path_locks_guard = threading.Lock()

    def __init__(self, path: str | Path, kind: str = "durable_json"):
        self._path = Path(path)
        self._kind = kind
        key = str(self._path.resolve())
        with DurableJsonStore._path_locks_guard:
            if key not in DurableJsonStore._path_locks:
                DurableJsonStore._path_locks[key] = threading.Lock()
            self._lock = DurableJsonStore._path_locks[key]

    # ── public API ──

    def read(self) -> dict:
        """Return the stored payload; {} when absent.

        Raises:
            DurableStoreError: when the main file is damaged AND journal
                recovery cannot produce a verified payload (fail-closed).
        """
        with self._lock:
            return self._read_locked()

    def write(self, payload: dict) -> dict:
        """Persist ``payload`` atomically; returns an outcome dict.

        Idempotent: writing the canonical-identical payload is a no-op.
        A store locked by another process fails closed
        (``{"success": False, "error": "store locked"}``).
        """
        canonical = _canonical(payload)
        with self._lock:
            with self._flocked() as locked:
                if not locked:
                    logger.warning("durable_store %s: locked by another writer", self._path.name)
                    return {"success": False, "error": "store locked"}
                current = self._read_quiet()
                if current == payload:
                    return {"success": True, "idempotent": True}
                envelope = {
                    "v": DURABLE_JSON_SCHEMA_VERSION,
                    "kind": self._kind,
                    "checksum": _checksum(canonical),
                    "payload": payload,
                }
                self._journal_put(envelope, canonical)
                self._atomic_replace(envelope)
            return {"success": True, "bytes": len(canonical)}

    def reset(self) -> None:
        """Drop main + journal contents (tests / lifecycle reset).

        Absence IS the empty state — an empty-text file would read as
        damaged under the checksum contract.
        """
        with self._lock:
            with self._flocked():
                self._path.unlink(missing_ok=True)
                self._journal_path().unlink(missing_ok=True)

    # ── internals ──

    def _journal_path(self) -> Path:
        return self._path.with_name(self._path.name + DURABLE_JOURNAL_SUFFIX)

    def _lock_path(self) -> Path:
        return self._path.with_name(self._path.name + DURABLE_LOCK_SUFFIX)

    @contextmanager
    def _flocked(self) -> Iterator[bool]:
        """Hold the advisory lock for the block; yields False when busy."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path(), os.O_CREAT | os.O_RDWR)
        try:
            if _HAVE_FCNTL:
                try:
                    _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                except OSError:
                    yield False
                    return
            try:
                yield True
            finally:
                if _HAVE_FCNTL:
                    _fcntl.flock(fd, _fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read_envelope_from(self, path: Path) -> dict | None:
        """Parse+verify one envelope file; None when absent/damaged."""
        try:
            raw = path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError):
            return None
        except OSError as e:
            logger.debug("durable_store %s: read failed: %s", path.name, e)
            return None
        try:
            env = json.loads(raw)
            if env.get("checksum") != _checksum(_canonical(env.get("payload"))):
                logger.warning("durable_store %s: checksum mismatch", path.name)
                return None
            migrated = check_and_migrate(env, env.get("kind", "durable_json"))
            return migrated.get("payload", {})
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("durable_store %s: damaged (%s)", path.name, e)
            return None

    def _read_quiet(self) -> dict:
        """Read without raising: main, else journal replay, else {}."""
        payload = self._read_envelope_from(self._path)
        if payload is not None:
            return payload
        recovered = self._read_journal_tail()
        if recovered is not None:
            return recovered
        return {}

    def _read_locked(self) -> dict:
        payload = self._read_envelope_from(self._path)
        if payload is not None:
            return payload
        recovered = self._read_journal_tail()
        if recovered is not None:
            logger.warning("durable_store %s: recovered payload from journal", self._path.name)
            self._self_heal(recovered)
            return recovered
        if self._path.exists():
            raise DurableStoreError(f"durable store {self._path.name} damaged beyond journal recovery")
        return {}

    def _read_journal_tail(self) -> dict | None:
        """Verify-and-return the LAST well-formed journal record."""
        jp = self._journal_path()
        try:
            lines = [ln for ln in jp.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (FileNotFoundError, OSError):
            return None
        for line in reversed(lines):
            try:
                rec = json.loads(line)
                env = rec.get("envelope", {})
                if env.get("checksum") == _checksum(_canonical(env.get("payload"))):
                    migrated = check_and_migrate(env, env.get("kind", "durable_json"))
                    return migrated.get("payload", {})
            except (ValueError, KeyError, TypeError):
                continue
        return None

    def _self_heal(self, payload: dict) -> None:
        """Best-effort rewrite of a damaged main file from journal truth."""
        try:
            envelope = {
                "v": DURABLE_JSON_SCHEMA_VERSION,
                "kind": self._kind,
                "checksum": _checksum(_canonical(payload)),
                "payload": payload,
            }
            self._atomic_replace(envelope)
            self._journal_put(envelope, _canonical(payload))
        except Exception as e:  # noqa: BLE001 — heal is best-effort by design
            logger.debug("durable_store %s: self-heal skipped: %s", self._path.name, e)

    def _journal_put(self, envelope: dict, canonical: str) -> None:
        """Mirror the last committed envelope into the journal (overwrite).

        The journal is a ONE-RECORD mirror, kept after the replace: a main
        file damaged at ANY later point still recovers the last known-good
        payload (P0.4 — truncated stores never lose records).
        """
        jp = self._journal_path()
        jp.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"envelope": envelope}, ensure_ascii=False, separators=(",", ":"))
        with open(jp, "w", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        del canonical

    def _atomic_replace(self, envelope: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
