"""File Editor — Diff Semantic Edit Engine + Atomic Batch + Patch System + Undo/Redo

Capabilities:
  diff_edit()       — Semantic search/replace with context-tolerant matching
  batch_edit()      — Atomic multi-file editing (all succeed or all roll back)
  patch_create/apply/revert — Patch lifecycle
  HistoryStack      — File operation history + reversal inference

Package layout (subpackaged from the former flat ``services/file_editor*.py``):
  __init__.py  — public surface (this facade; re-exports below)
  models.py    — DiffEdit / EditOperation / Patch dataclasses
  engine.py    — EditEngine + get_engine singleton
  patch.py     — PatchManager + get_patch_manager singleton
  handlers.py  — fs/* API handler adapters

API (via LOG_ROUTES registration):
  POST /api/fs/edit         — Semantic edit
  POST /api/fs/batch_edit   — Atomic batch edit
  GET  /api/fs/history      — Operation history
  POST /api/fs/undo         — Rollback
  POST /api/fs/redo         — Redo
  POST /api/fs/patch        — Create patch from changes
  POST /api/fs/patch/apply  — Apply patch
  POST /api/fs/patch/revert — Revert patch
"""

from __future__ import annotations

from .engine import EditEngine, get_engine  # noqa: F401 — re-export
from .handlers import (  # noqa: F401 — re-export
    handle_fs_batch_edit,
    handle_fs_edit,
    handle_fs_history,
    handle_fs_patch_apply,
    handle_fs_patch_create,
    handle_fs_patch_get,
    handle_fs_patch_list,
    handle_fs_patch_revert,
    handle_fs_redo,
    handle_fs_undo,
)
from .models import DiffEdit, EditOperation, Patch  # noqa: F401 — re-export
from .patch import PatchManager, get_patch_manager  # noqa: F401 — re-export

__all__ = [
    "DiffEdit",
    "EditOperation",
    "Patch",
    "EditEngine",
    "PatchManager",
    "get_engine",
    "get_patch_manager",
    "handle_fs_edit",
    "handle_fs_batch_edit",
    "handle_fs_history",
    "handle_fs_undo",
    "handle_fs_redo",
    "handle_fs_patch_create",
    "handle_fs_patch_apply",
    "handle_fs_patch_revert",
    "handle_fs_patch_list",
    "handle_fs_patch_get",
]
