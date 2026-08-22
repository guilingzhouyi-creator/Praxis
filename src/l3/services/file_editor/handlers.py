"""File editor — API handler adapters (fs/* routes).

Extracted from ``file_editor.py``: the thin request-body adapters that map
HTTP/API payloads onto EditEngine / PatchManager calls. Logic lives in
``engine.py`` / ``patch.py``.
"""

from __future__ import annotations

from .engine import get_engine
from .models import DiffEdit
from .patch import get_patch_manager


def handle_fs_edit(body: dict | None = None) -> dict:
    """POST /api/fs/edit — Semantic file edit"""
    b = body or {}
    path = b.get("path", "")
    old_str = b.get("old_str", "")
    new_str = b.get("new_str", "")
    if not path or not old_str:
        return {"success": False, "error": "path and old_str are required"}
    edit = DiffEdit(
        path=path,
        old_str=old_str,
        new_str=new_str or "",
        description=b.get("description", ""),
        start_line=b.get("start_line", 0),
        end_line=b.get("end_line", 0),
        case_sensitive=b.get("case_sensitive", True),
    )
    return get_engine().diff_edit(edit)


def handle_fs_batch_edit(body: dict | None = None) -> dict:
    """POST /api/fs/batch_edit — Atomic multi-file edit"""
    b = body or {}
    raw_edits = b.get("edits", [])
    if not raw_edits:
        return {"success": False, "error": "edits required"}
    edits = [DiffEdit(**e) for e in raw_edits]
    return get_engine().batch_edit(
        edits,
        description=b.get("description", ""),
        agent_id=b.get("agent_id", ""),
    )


def handle_fs_history(body: dict | None = None) -> dict:
    """GET /api/fs/history — File operation history"""
    b = body or {}
    limit = b.get("limit", 50)
    return get_engine().history(limit=limit)


def handle_fs_undo(body: dict | None = None) -> dict:
    """POST /api/fs/undo — Rollback operation"""
    b = body or {}
    op_id = b.get("operation_id", "")
    return get_engine().undo(operation_id=op_id)


def handle_fs_redo(body: dict | None = None) -> dict:
    """POST /api/fs/redo — Redo operation"""
    return get_engine().redo()


def handle_fs_patch_create(body: dict | None = None) -> dict:
    """POST /api/fs/patch — Create patch from history"""
    b = body or {}
    op_id = b.get("operation_id", "")
    if not op_id:
        return {"success": False, "error": "operation_id required"}
    return get_patch_manager().create_from_history(
        operation_id=op_id,
        description=b.get("description", ""),
        author=b.get("author", ""),
    )


def handle_fs_patch_apply(body: dict | None = None) -> dict:
    """POST /api/fs/patch/apply — Apply patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().apply(patch_id)


def handle_fs_patch_revert(body: dict | None = None) -> dict:
    """POST /api/fs/patch/revert — Revert patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().revert(patch_id)


def handle_fs_patch_list(body: dict | None = None) -> dict:
    """GET /api/fs/patches — List all patches"""
    return get_patch_manager().list_patches()


def handle_fs_patch_get(body: dict | None = None) -> dict:
    """POST /api/fs/patch/get — Get single patch"""
    b = body or {}
    patch_id = b.get("patch_id", "")
    if not patch_id:
        return {"success": False, "error": "patch_id required"}
    return get_patch_manager().get_patch(patch_id)
