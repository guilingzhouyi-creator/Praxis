"""Backup and disaster-recovery service for Praxis runtime state.

Copies the persistent ``data_dir`` tree (memory rings, RC channel, sandbox
journal, lifecycle state, sessions, …) into timestamped ``backups/``
snapshots, and restores from them. Supports ad-hoc CLI backups, scheduled
auto-backup at boot, and export/import of a snapshot as a tarball.

Module docstring: this module provides backup/recovery, mirroring
``memory_init.snapshot_cells`` at the directory level.
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import threading
from datetime import UTC, datetime

from l1.kernel.params.system import BACKUP_AUTO_INTERVAL, BACKUP_KEEP_MAX, LOG_TRUNC_120
from l1.kernel.paths import data_dir

logger = logging.getLogger(__name__)

BACKUPS_SUBDIR = "backups"
BACKUP_TS_FORMAT = "%Y%m%dT%H%M%S"


def _backups_dir() -> str:
    """Return the backups root under data_dir."""
    return os.path.join(data_dir(), BACKUPS_SUBDIR)


def _ensure_backups_dir() -> str:
    os.makedirs(_backups_dir(), exist_ok=True)
    return _backups_dir()


def _snapshot_dir(ts: str | None = None) -> str:
    ts = ts or datetime.now(UTC).strftime(BACKUP_TS_FORMAT)
    return os.path.join(_backups_dir(), ts)


def create_backup(tag: str = "") -> dict:
    """Copy the current data_dir tree into a timestamped backup snapshot.

    Returns ``{success, backup, path, copied_files, bytes}``. The snapshot
    is an independent copy, so a later disaster can restore it.
    """
    src = data_dir()
    if not os.path.isdir(src):
        return {"success": False, "error": f"data_dir not found: {src}"}
    ts = datetime.now(UTC).strftime(BACKUP_TS_FORMAT)
    if tag:
        ts = f"{ts}_{tag}"
    dst = _snapshot_dir(ts)
    try:
        os.makedirs(dst, exist_ok=True)
        copied = 0
        total_bytes = 0
        for root, _dirs, files in os.walk(src):
            rel_root = os.path.relpath(root, src)
            if rel_root == BACKUPS_SUBDIR:
                continue  # never nest backups inside backups
            for fname in files:
                src_file = os.path.join(root, fname)
                rel = os.path.join(rel_root, fname) if rel_root != "." else fname
                dst_file = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(dst_file) or dst, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                copied += 1
                total_bytes += os.path.getsize(src_file)
        _prune_old_backups()
        return {"success": True, "backup": ts, "path": dst, "copied_files": copied, "bytes": total_bytes}
    except Exception as e:
        logger.warning("backup failed: %s", e)
        return {"success": False, "error": str(e)}


def list_backups() -> list[dict]:
    """List available backups newest-first with size and file counts."""
    root = _backups_dir()
    if not os.path.isdir(root):
        return []
    entries = []
    for name in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        n_files = sum(len(fs) for _r, _d, fs in os.walk(path))
        total = sum(os.path.getsize(os.path.join(_r, f)) for _r, _d, fs in os.walk(path) for f in fs)
        entries.append({"backup": name, "path": path, "files": n_files, "bytes": total})
    return entries


def restore_backup(name: str) -> dict:
    """Restore data_dir from a named backup snapshot (destructive).

    The current data_dir is replaced by the snapshot contents. Intended for
    disaster recovery after data loss or corruption.
    """
    src = os.path.join(_backups_dir(), name)
    if not os.path.isdir(src):
        return {"success": False, "error": f"backup not found: {name}"}
    dst = data_dir()
    try:
        os.makedirs(dst, exist_ok=True)
        restored = 0
        for root, _dirs, files in os.walk(src):
            rel_root = os.path.relpath(root, src)
            for fname in files:
                src_file = os.path.join(root, fname)
                rel = os.path.join(rel_root, fname) if rel_root != "." else fname
                dst_file = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(dst_file) or dst, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                restored += 1
        return {"success": True, "backup": name, "restored_files": restored}
    except Exception as e:
        logger.warning("restore failed: %s", e)
        return {"success": False, "error": str(e)}


def export_backup(name: str, target: str = "") -> dict:
    """Export a backup snapshot as a tarball to ``target`` (default: data_dir)."""
    src = os.path.join(_backups_dir(), name)
    if not os.path.isdir(src):
        return {"success": False, "error": f"backup not found: {name}"}
    target = target or os.path.join(data_dir(), f"backup_{name}.tar.gz")
    try:
        with tarfile.open(target, "w:gz") as tar:
            tar.add(src, arcname=name)
        return {"success": True, "path": target, "size": os.path.getsize(target)}
    except Exception as e:
        logger.warning("export backup failed: %s", e)
        return {"success": False, "error": str(e)}


def import_backup(tarball: str) -> dict:
    """Import a backup tarball into backups/ and return the snapshot name."""
    if not os.path.isfile(tarball):
        return {"success": False, "error": f"tarball not found: {tarball}"}
    ts = datetime.now(UTC).strftime(BACKUP_TS_FORMAT)
    dst = _snapshot_dir(ts)
    try:
        os.makedirs(dst, exist_ok=True)
        with tarfile.open(tarball, "r:gz") as tar:
            members = tar.getmembers()
            # Members carry the original snapshot dir as their top-level dir.
            for m in members:
                if m.isdir():
                    continue
                rel = os.path.relpath(m.name, m.name.split("/")[0])
                if rel.startswith(".."):
                    continue
                f = tar.extractfile(m)
                if f is None:
                    continue
                out = os.path.join(dst, rel)
                os.makedirs(os.path.dirname(out) or dst, exist_ok=True)
                with open(out, "wb") as w:
                    shutil.copyfileobj(f, w)
        return {"success": True, "backup": ts, "path": dst, "files": len(members)}
    except Exception as e:
        logger.warning("import backup failed: %s", e)
        return {"success": False, "error": str(e)}


def _prune_old_backups() -> None:
    """Keep only the most recent BACKUP_KEEP_MAX snapshots."""
    root = _backups_dir()
    if not os.path.isdir(root):
        return
    entries = sorted(
        (os.path.join(root, n) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))),
        key=os.path.getmtime,
        reverse=True,
    )
    for old in entries[BACKUP_KEEP_MAX:]:
        try:
            shutil.rmtree(old)
            logger.info("pruned old backup %s", old[:LOG_TRUNC_120])
        except OSError as e:
            logger.debug("prune failed %s: %s", old, e)


# ── Scheduled auto-backup ──

_backup_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_auto_backup(interval: float = BACKUP_AUTO_INTERVAL) -> dict:
    """Start a daemon thread creating a backup every ``interval`` seconds.

    Idempotent: repeated calls return the already-running thread.
    """
    global _backup_thread
    if _backup_thread and _backup_thread.is_alive():
        return {"success": True, "running": True, "interval": interval}
    _stop_event.clear()

    def _loop() -> None:
        while not _stop_event.is_set():
            _stop_event.wait(interval)
            if _stop_event.is_set():
                break
            r = create_backup(tag="auto")
            if not r.get("success"):
                logger.warning("auto-backup failed: %s", r.get("error", ""))

    _backup_thread = threading.Thread(target=_loop, name="praxis-backup", daemon=True)
    _backup_thread.start()
    return {"success": True, "running": True, "interval": interval}


def stop_auto_backup() -> dict:
    """Stop the scheduled auto-backup thread."""
    _stop_event.set()
    return {"success": True, "stopped": True}


def reset_backup() -> None:
    """Stop the auto-backup thread (test/conftest reset hook)."""
    stop_auto_backup()
