"""PersistableMixin — atomic JSON persistence for in-memory services.

Every service that subclasses this gets:
  - _persist_path: path to JSON file (configurable via params)
  - _persist()    — atomic write (tmp + replace)
  - _restore()    — read + version check + migrate
  - _auto_save()  — periodic background save via daemon thread

Usage:
  class MyService(PersistableMixin):
      persistence_kind = "card_registry"
      def _serialize(self) -> dict: ...
      def _deserialize(self, data: dict) -> bool: ...
"""

from __future__ import annotations

import json
import logging
import os
import threading
import weakref
from abc import ABC, abstractmethod

from l1.kernel.versioning import check_and_migrate, stamp

logger = logging.getLogger(__name__)


class _PersistencePathState:
    """Coordinate serialized commits for one persistence path."""

    def __init__(self) -> None:
        self.write_lock = threading.Lock()
        self.epoch_lock = threading.Lock()
        self.next_epoch = 0
        self.committed_epoch = 0


_path_states: weakref.WeakValueDictionary[str, _PersistencePathState] = weakref.WeakValueDictionary()
_path_states_lock = threading.Lock()


def _get_path_state(path: str) -> _PersistencePathState:
    """Return the shared write coordinator for a persistence path."""
    with _path_states_lock:
        state = _path_states.get(path)
        if state is None:
            state = _PersistencePathState()
            _path_states[path] = state
        return state


class PersistableMixin(ABC):
    """Provide synchronized atomic JSON persistence and managed auto-save workers."""

    persistence_kind: str = ""
    _persist_path: str = ""
    _auto_save_interval: float = 30.0
    _lock: threading.RLock | None = None
    _auto_save_stop: threading.Event | None = None
    _auto_save_thread: threading.Thread | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def _init_persistence(self, persist_path: str, auto_save_interval: float = 30.0) -> None:
        """Initialize persistence coordination for the owning service."""
        self._persist_path = persist_path
        self._auto_save_interval = auto_save_interval
        self._path_state = _get_path_state(persist_path) if persist_path else None
        self._auto_save_control_lock = threading.Lock()
        self._auto_save_state_lock = threading.RLock()
        self._auto_save_generation = 0
        self._auto_save_stop = None
        self._auto_save_thread = None

    @abstractmethod
    def _serialize(self) -> dict: ...

    @abstractmethod
    def _deserialize(self, data: dict) -> bool: ...

    def save(self) -> dict:
        """Public: save current state to disk."""
        return self._persist()

    def load(self) -> dict:
        """Public: reload state from disk."""
        return self._restore()

    def _persist(self, _auto_save_generation: int | None = None) -> dict:
        """Write a consistent snapshot to disk, superseding older snapshots."""
        if not self._persist_path:
            return {"success": True, "skipped": True, "reason": "persistence disabled"}
        lock = self._lock
        try:
            if lock is None:
                data = dict(self._serialize())
            else:
                with lock:
                    data = dict(self._serialize())
            payload = json.dumps(stamp(data, self.persistence_kind), indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("persist %s snapshot: %s", self.persistence_kind, e)
            return {"success": False, "error": str(e)}

        with self._auto_save_state_lock:
            if _auto_save_generation is not None and _auto_save_generation != self._auto_save_generation:
                return {"success": False, "skipped": True, "reason": "auto-save stopped"}
            path_state = self._path_state
            assert path_state is not None, "persistence path state must exist for a configured path"
            with path_state.epoch_lock:
                path_state.next_epoch += 1
                epoch = path_state.next_epoch

        try:
            with path_state.write_lock:
                with path_state.epoch_lock:
                    if epoch < path_state.committed_epoch:
                        return {"success": False, "skipped": True, "reason": "superseded"}
                tmp = self._persist_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, self._persist_path)
                with path_state.epoch_lock:
                    path_state.committed_epoch = epoch
            return {"success": True, "path": self._persist_path}
        except Exception as e:
            logger.warning("persist %s: %s", self.persistence_kind, e)
            return {"success": False, "error": str(e)}

    def _restore(self) -> dict:
        """Restore a persisted snapshot into the owning service."""
        if not self._persist_path:
            return {"success": False, "error": "no persistence path"}
        if not os.path.exists(self._persist_path):
            return {"success": False, "error": "no file"}
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {"success": False, "error": f"read failed: {e}"}
        try:
            data = check_and_migrate(data, self.persistence_kind)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        try:
            lock = self._lock
            if lock is None:
                ok = self._deserialize(data)
            else:
                with lock:
                    ok = self._deserialize(data)
        except Exception as e:
            return {"success": False, "error": f"deserialize failed: {e}"}
        return {"success": ok, "entries": len(data)}

    def _start_auto_save(self) -> None:
        """Start one auto-save worker, terminating any earlier worker first."""
        with self._auto_save_control_lock:
            self._stop_auto_save_locked()
            stop = threading.Event()
            with self._auto_save_state_lock:
                self._auto_save_generation += 1
                generation = self._auto_save_generation
                self._auto_save_stop = stop

            owner = weakref.ref(self)

            def _loop() -> None:
                while not stop.wait(self._auto_save_interval):
                    instance = owner()
                    if instance is None:
                        break
                    instance._persist(generation)

            worker = threading.Thread(target=_loop, daemon=True, name=f"autosave-{self.persistence_kind}")
            with self._auto_save_state_lock:
                self._auto_save_thread = worker
            worker.start()

    def _stop_auto_save_locked(self) -> None:
        """Signal and wait for the current worker while its control lock is held."""
        from l1.kernel.params.system import PERSIST_AUTO_SAVE_STOP_TIMEOUT

        with self._auto_save_state_lock:
            self._auto_save_generation += 1
            stop = self._auto_save_stop
            worker = self._auto_save_thread
            self._auto_save_stop = None
            self._auto_save_thread = None
        if stop is not None:
            stop.set()
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(PERSIST_AUTO_SAVE_STOP_TIMEOUT)

    def _stop_auto_save(self) -> None:
        """Stop and join the active auto-save worker when called during teardown."""
        with self._auto_save_control_lock:
            self._stop_auto_save_locked()
