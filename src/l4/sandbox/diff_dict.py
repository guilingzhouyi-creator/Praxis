"""Shared Zstd dictionary (Phase 2, L2 review frames) — declarative, optional.

Trains a 64KB dictionary from code samples declared in
``config/discovery/diff_languages.yaml`` (``diff_dictionary:`` section) and
persists it to data_dir (``DIFF_DICTIONARY_FILE``). The L2 review-frame
codec uses it for high-compression zstd; when zstandard is unavailable, the
dictionary is absent, or the feature is disabled, everything degrades to
plain zlib — zstd is an enhancement, never a hard dependency.

``train_dictionary`` / ``load_dictionary`` / ``get_dictionary`` are the
public surface; ``get_dictionary`` returns None when unavailable.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, cast

from l1.kernel.params.system import DIFF_DICTIONARY_FILE

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLES = ("src", "tests", "config")
_DEFAULT_SIZE = 65536  # 64KB dictionary
_DEFAULT_TRAINING_LEVEL = 19


def _registry_config() -> dict[str, Any]:
    """Read the declarative ``diff_dictionary:`` section (never raises)."""
    try:
        import yaml

        from l4.sandbox.diff_language import DiffLanguageRegistry

        # Reuse the language registry's repo-root config resolution.
        p = Path(DiffLanguageRegistry._default_path())
        if not p.exists():
            return {}
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return dict(data.get("diff_dictionary") or {})
    except Exception as e:
        logger.debug("diff_dict: config load skipped: %s", e)
        return {}


def _persist_path() -> str:
    """Resolve the dictionary file under data_dir (falls back to cwd)."""
    try:
        from l1.kernel.paths import get_paths

        return get_paths().diff_dictionary_file
    except Exception as e:
        logger.debug("diff_dict: path resolve skipped: %s", e)
        return DIFF_DICTIONARY_FILE


def _collect_samples(roots: list[str]) -> list[bytes]:
    """Collect code samples from the declared root directories."""
    samples: list[bytes] = []
    try:
        from l4.sandbox.diff_language import get_registry

        reg = get_registry()
        repo = Path(__file__).resolve().parent.parent.parent.parent
        for root in roots or _DEFAULT_SAMPLES:
            base = Path(root)
            if not base.is_absolute():
                base = repo / root
            if not base.is_dir():
                continue
            for p in base.rglob("*"):
                if p.suffix not in (".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".h", ".cpp"):
                    continue
                if "node_modules" in p.parts or ".venv" in p.parts or p.name.startswith("."):
                    continue
                try:
                    samples.append(p.read_bytes()[: 4 * 1024])
                except Exception:
                    continue
                if len(samples) >= 512:
                    break
            if len(samples) >= 512:
                break
        # Language registry stays warm but unused here; keep import honest.
        _ = reg
    except Exception as e:
        logger.debug("diff_dict: sample collection skipped: %s", e)
    return samples


def train_dictionary(path: str = "", force: bool = False) -> dict:
    """Train and persist the shared Zstd dictionary from declared samples.

    Args:
        path: Override the persist path (tests). Defaults to data_dir.
        force: Re-train even when a dictionary already exists.

    Returns:
        ``{"success": bool, "path": ..., "bytes": N, "samples": N}`` —
        success False when zstandard is unavailable or no samples found.
    """
    try:
        import zstandard  # noqa: F401  (hard requirement only when enabled)
    except Exception as e:
        logger.debug("diff_dict: zstandard unavailable: %s", e)
        return {"success": False, "reason": "zstandard not installed"}

    cfg = _registry_config()
    if not cfg.get("enabled", True):
        return {"success": False, "reason": "diff_dictionary disabled by config"}
    target = path or _persist_path()
    if not force and Path(target).exists():
        return {"success": True, "path": target, "bytes": Path(target).stat().st_size, "samples": 0, "cached": True}

    roots = cfg.get("samples_dir") or list(_DEFAULT_SAMPLES)
    if isinstance(roots, str):
        roots = [roots]
    samples = _collect_samples(list(roots))
    if len(samples) < 8:
        return {"success": False, "reason": f"too few samples ({len(samples)})"}

    import zstandard

    size = int(cfg.get("size_bytes", _DEFAULT_SIZE))
    # zstandard.train_dictionary is typed for a wider buffer list; samples are
    # bytes at runtime, so cast via string type (runtime-safe — `memoryview[int]`
    # as a real annotation would be evaluated and is not subscriptable).
    dict_data = zstandard.train_dictionary(size, cast("list[bytes | bytearray | memoryview[int]]", samples))
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_bytes(dict_data.as_bytes())
    logger.info("diff_dict: trained %d-byte dictionary from %d samples → %s", size, len(samples), target)
    return {"success": True, "path": target, "bytes": len(dict_data.as_bytes()), "samples": len(samples)}


def load_dictionary(path: str = "") -> bytes | None:
    """Load the shared dictionary bytes (None when absent/unreadable)."""
    p = path or _persist_path()
    try:
        if not Path(p).exists():
            return None
        data = Path(p).read_bytes()
        return data if data else None
    except Exception as e:
        logger.debug("diff_dict: dictionary load skipped: %s", e)
        return None


# ── Singleton cache ─────────────────────────────────────────────────────

_cache: bytes | None = None
_cache_loaded = False
_cache_lock = threading.Lock()


def get_dictionary() -> bytes | None:
    """Get the cached shared dictionary (None when unavailable).

    Loads once; call ``invalidate_dictionary`` to force a reload after a
    training run. Never raises.
    """
    global _cache, _cache_loaded
    if not _cache_loaded:
        with _cache_lock:
            if not _cache_loaded:
                _cache = load_dictionary()
                _cache_loaded = True
    return _cache


def invalidate_dictionary() -> None:
    """Drop the cached dictionary (call after train_dictionary)."""
    global _cache, _cache_loaded
    with _cache_lock:
        _cache = None
        _cache_loaded = False


def status() -> dict:
    """Dictionary status for the status surface."""
    data = get_dictionary()
    return {
        "available": data is not None,
        "bytes": len(data) if data else 0,
        "path": _persist_path(),
        "config": _registry_config().get("enabled", True),
    }
