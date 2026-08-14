"""ShellFamily — config-loaded registry of shell dialects with frontend bindings."""

from __future__ import annotations

import importlib
import logging
import threading

from .base import Shell

logger = logging.getLogger(__name__)


class ShellFamily:
    """Registry of shell dialects with frontend bindings and a default shell.

    Members are declared in config (``config/discovery/shells.yaml``,
    overridable via the praxis.yaml ``shells:`` section) and instantiated
    generically from module/class names — no shell is hardcoded here.  The
    revision counter bumps on every structural change so consumers can
    cache snapshots.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._shells: dict[str, Shell] = {}
        self._bindings: dict[str, str] = {}
        self._default: str = ""
        self._revision: int = 0

    def register(self, shell: Shell, bindings: list[str] | None = None) -> None:
        """Register a shell dialect, optionally binding frontend names to it."""
        if not shell.name:
            raise ValueError("shell must declare a non-empty name")
        with self._lock:
            self._shells[shell.name] = shell
            if bindings:
                for frontend in bindings:
                    self._bindings[frontend] = shell.name
            if not self._default:
                self._default = shell.name
            self._revision += 1

    def unregister(self, name: str) -> None:
        """Unregister a shell and drop its bindings and default reference."""
        with self._lock:
            self._shells.pop(name, None)
            self._bindings = {k: v for k, v in self._bindings.items() if v != name}
            if self._default == name:
                self._default = next(iter(self._shells), "")
            self._revision += 1

    def get(self, name: str) -> Shell:
        """Return the registered shell by name; raises KeyError when absent."""
        with self._lock:
            return self._shells[name]

    def list(self) -> list[str]:
        """Return the names of all registered shells (sorted)."""
        with self._lock:
            return sorted(self._shells)

    def default(self) -> Shell:
        """Return the default shell; falls back to the first registered one."""
        with self._lock:
            if self._default and self._default in self._shells:
                return self._shells[self._default]
            if self._shells:
                return next(iter(self._shells.values()))
            raise KeyError("no shell registered")

    def bind(self, frontend: str, shell_name: str) -> None:
        """Bind a frontend name to a registered shell name."""
        with self._lock:
            if shell_name not in self._shells:
                raise KeyError(f"unknown shell: {shell_name}")
            self._bindings[frontend] = shell_name
            self._revision += 1

    def resolve(self, frontend: str) -> Shell:
        """Return the shell bound to a frontend; falls back to the default shell."""
        with self._lock:
            name = self._bindings.get(frontend) or self._default
            if name and name in self._shells:
                return self._shells[name]
            raise KeyError(f"no shell for frontend: {frontend}")

    def load_config(self, cfg: dict) -> int:
        """Instantiate declared shells from config and apply bindings/default.

        ``cfg`` is the merged ``shells`` config section (params defaults ←
        discovery shells.yaml ← praxis.yaml overrides):

        - ``enabled``  — master switch; False leaves the family empty
        - ``shells``   — {name: {"module": m, "class": C}} member factories
        - ``bindings`` — {frontend: shell_name} resolution hints
        - ``default``  — shell used when no binding matches

        Returns the number of successfully instantiated members; failing
        members are logged and skipped so one bad spec never blocks the rest.
        """
        with self._lock:
            if not cfg or cfg.get("enabled") is False:
                return 0
            declared = cfg.get("shells") or {}
            count = 0
            for name, spec in declared.items():
                if not isinstance(spec, dict) or "module" not in spec or "class" not in spec:
                    logger.warning("shells: invalid spec for %s (module/class required)", name)
                    continue
                try:
                    module = importlib.import_module(spec["module"])
                    cls = getattr(module, spec["class"])
                    self.register(cls())
                    count += 1
                except Exception as e:
                    logger.warning("shells: failed to load %s: %s", name, e)
            bindings = cfg.get("bindings") or {}
            for frontend, shell_name in bindings.items():
                if shell_name in self._shells:
                    self._bindings[frontend] = shell_name
            if cfg.get("default") and cfg["default"] in self._shells:
                self._default = cfg["default"]
            if bindings or cfg.get("default"):
                self._revision += 1
            return count

    def revision(self) -> int:
        """Return the structural revision counter (bumps on any change)."""
        with self._lock:
            return self._revision

    def snapshot(self) -> dict:
        """Return an immutable snapshot of shells, bindings, and default."""
        with self._lock:
            return {
                "shells": dict(self._shells),
                "bindings": dict(self._bindings),
                "default": self._default,
                "revision": self._revision,
            }


_family = ShellFamily()


def get_family() -> ShellFamily:
    """Return the process-wide ShellFamily singleton."""
    return _family


def reset_family() -> ShellFamily:
    """Replace the process-wide family with a fresh empty one (tests)."""
    global _family
    _family = ShellFamily()
    return _family
