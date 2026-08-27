"""File editor — PatchManager (create/apply/revert/serialize).

Extracted from ``file_editor.py``: the patch manager and its process-wide
singleton. Depends on the EditEngine for batch application; models live in
``models.py``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from l1.kernel.params.system import PATCH_JSON_FILE

from .models import DiffEdit, Patch

logger = logging.getLogger(__name__)


class PatchManager:
    """Patch management — create/apply/revert/serialize."""

    def __init__(self, engine, patch_dir: str = ""):
        self._engine = engine
        self._patches: dict[str, Patch] = {}
        self._lock = threading.RLock()
        from l1.kernel.paths import get_paths as _gp

        # Patches are runtime state — keep them under the data dir, not the
        # config dir (config_dir is for user-editable config; see B3 layout).
        self._patch_dir = Path(patch_dir or Path(_gp().data_dir) / "patches")
        self._patch_dir.mkdir(parents=True, exist_ok=True)

    def create_from_history(self, operation_id: str, description: str = "", author: str = "") -> dict:
        """Create a patch from history operations."""
        with self._engine._lock:
            op = next((o for o in self._engine._history if o.id == operation_id), None)
        if not op:
            return {"success": False, "error": f"operation not found: {operation_id}"}

        patch = Patch(
            description=description or op.description,
            author=author,
            changes=op.edits,
        )

        with self._lock:
            self._patches[patch.id] = patch
            # Persist to disk
            self._save(patch)

        return {"success": True, "patch": patch.to_dict()}

    def apply(self, patch_id: str) -> dict:
        """Apply a stored patch to the target file if it has not already been applied."""
        with self._lock:
            patch = self._patches.get(patch_id)
        if not patch:
            return {"success": False, "error": f"patch not found: {patch_id}"}
        if patch.applied:
            return {"success": False, "error": "patch already applied"}

        edits = []
        for c in patch.changes:
            edits.append(
                DiffEdit(
                    path=c["path"],
                    old_str=c["old"],
                    new_str=c["new"],
                    description=patch.description,
                )
            )

        result = self._engine.batch_edit(edits, description=f"patch: {patch.description}")
        if result.get("success"):
            patch.applied = True
            self._save(patch)

        return result

    def revert(self, patch_id: str) -> dict:
        """Revert an applied patch."""
        with self._lock:
            patch = self._patches.get(patch_id)
        if not patch:
            return {"success": False, "error": f"patch not found: {patch_id}"}
        if not patch.applied:
            return {"success": False, "error": "patch not applied"}
        if patch.reverted:
            return {"success": False, "error": "patch already reverted"}

        # Reverse changes and execute undo
        edits = []
        for c in reversed(patch.changes):
            edits.append(
                DiffEdit(
                    path=c["path"],
                    old_str=c["new"],  # Swap old and new
                    new_str=c["old"],
                    description=f"revert: {patch.description}",
                )
            )

        result = self._engine.batch_edit(edits, description=f"revert patch: {patch.description}")
        if result.get("success"):
            patch.reverted = True
            self._save(patch)

        return result

    def list_patches(self) -> dict:
        """List all registered patches."""
        with self._lock:
            return {
                "success": True,
                "count": len(self._patches),
                "patches": [p.to_dict() for p in self._patches.values()],
            }

    def get_patch(self, patch_id: str) -> dict:
        """Return the patch with the given id, or an error dict."""
        with self._lock:
            patch = self._patches.get(patch_id)
        if not patch:
            return {"success": False, "error": "patch not found"}
        return {"success": True, "patch": patch.to_dict()}

    def _save(self, patch: Patch) -> None:
        """Persist patch to disk."""
        try:
            path = self._patch_dir / PATCH_JSON_FILE.format(patch_id=patch.id)
            path.write_text(patch.to_json(), encoding="utf-8")
        except OSError as e:
            logger.warning("patch save failed: %s", e)

    def _load_all(self) -> None:
        """Load all patches from disk at startup."""
        if not self._patch_dir.exists():
            return
        for f in self._patch_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                patch = Patch(**{k: v for k, v in data.items() if k in Patch.__dataclass_fields__})
                self._patches[patch.id] = patch
            except (OSError, ValueError, json.JSONDecodeError) as e:
                logger.warning("patch load failed: %s: %s", f.name, e)


# ── Global singleton ──

_patch_manager: PatchManager | None = None
_patch_lock = threading.Lock()


def get_patch_manager() -> PatchManager:
    """Return the shared PatchManager singleton, creating it on first use."""
    global _patch_manager
    if _patch_manager is None:
        with _patch_lock:
            if _patch_manager is None:
                from .engine import get_engine

                _patch_manager = PatchManager(get_engine())
                _patch_manager._load_all()
    return _patch_manager


def reset_patch_manager() -> None:
    """Reset the singleton (used by tests, conftest _RESETS)."""
    global _patch_manager
    with _patch_lock:
        _patch_manager = None
