"""File Editor — Diff Semantic Edit Engine + Atomic Batch + Patch System + Undo/Redo

Architecture:
  FileEditor (services/file_editor.py — facade)
  ├── diff_edit()       — Semantic search/replace with context-tolerant matching
  ├── batch_edit()      — Atomic multi-file editing (all succeed or all roll back)
  ├── patch_create()    — Create a patch from changes
  ├── patch_apply()     — Apply a patch
  ├── patch_revert()    — Revert a patch
  └── HistoryStack      — File operation history stack + reversal inference

Module layout (split from the original monolith for readability):
  file_editor_models.py    — DiffEdit / EditOperation / Patch dataclasses
  file_editor_engine.py    — EditEngine + get_engine singleton
  file_editor_patch.py     — PatchManager + get_patch_manager singleton
  file_editor_handlers.py  — fs/* API handler adapters
  file_editor.py           — re-export facade (public surface unchanged)

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

from .file_editor_engine import EditEngine, get_engine  # noqa: F401 — re-export
from .file_editor_handlers import (  # noqa: F401 — re-export
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
from .file_editor_models import DiffEdit, EditOperation, Patch  # noqa: F401 — re-export
from .file_editor_patch import PatchManager, get_patch_manager  # noqa: F401 — re-export

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
