"""File editor — EditEngine (diff semantic matching + atomic batch + undo/redo).

Extracted from ``file_editor.py``: the edit engine and its process-wide
singleton. The data models live in ``file_editor_models.py``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from l1.kernel.params.system import FILE_EDITOR_MAX_HISTORY, LOG_TRUNC_100

from .file_editor_models import DiffEdit, EditOperation

logger = logging.getLogger(__name__)


class EditEngine:
    """File edit engine — Diff semantic matching + atomic batch + history stack."""

    def __init__(self, max_history: int = FILE_EDITOR_MAX_HISTORY):
        self._history: list[EditOperation] = []
        self._redo_stack: list[EditOperation] = []
        self._lock = threading.RLock()
        self._max_history = max_history

    # ── Diff Semantic Edit ──

    def diff_edit(self, edit: DiffEdit) -> dict:
        """Execute semantic search/replace edit.

        Supports:
          - Exact match (default)
          - Context-tolerant match (ignores leading/trailing whitespace differences)
          - Line range restriction
        """
        path = Path(edit.path)
        if not path.exists():
            return {"success": False, "error": f"file not found: {edit.path}", "file": str(edit.path)}

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {"success": False, "error": f"read failed: {e}", "file": str(edit.path)}

        old = edit.old_str
        new = edit.new_str

        # Line range extraction
        if edit.start_line > 0 and edit.end_line > 0:
            lines = content.splitlines(keepends=True)
            if edit.start_line < 1 or edit.end_line > len(lines):
                return {
                    "success": False,
                    "error": "line range out of bounds",
                    "file": str(edit.path),
                    "line": edit.start_line,
                }
            target = "".join(lines[edit.start_line - 1 : edit.end_line])
        else:
            target = content

        # Semantic matching
        idx = self._match(target, old, edit.case_sensitive)
        if idx < 0:
            return {"success": False, "error": "old_str not found (try adjusting context)", "file": str(edit.path)}

        new_content = target[:idx] + new + target[idx + len(old) :]

        # Write back to file
        if edit.start_line > 0 and edit.end_line > 0:
            lines[edit.start_line - 1 : edit.end_line] = [new_content]
            final = "".join(lines)
        else:
            final = new_content

        try:
            from l3.resource_buffer.manager import get_manager

            get_manager().stage(str(path), final, op="edit")
        except (ImportError, AttributeError) as e:
            return {"success": False, "error": f"buffer stage failed: {e}", "file": str(path)}

        # Write back to disk (batch_edit parity) — buffer stage records the
        # sandbox intent; the file itself must reflect the edit so undo/redo
        # and direct readers see the change.
        try:
            path.write_text(final, encoding="utf-8")
        except OSError as e:
            return {"success": False, "error": f"write failed: {e}", "file": str(path)}

        op = EditOperation(
            edits=[{"path": str(path), "old": old, "new": new, "line": edit.start_line or 1}],
            description=edit.description or f"edit {path.name}",
        )
        self._push(op)

        # Reference Channel: record human correction for training data
        try:
            from l3.bus.reference_channel import get_rc as _rc

            _rc().human_correction("", "", "content", old, new, reason=f"edit {path.name}")
        except (ImportError, AttributeError):
            logger.debug("file_editor: rc correction failed")

        return {
            "success": True,
            "path": str(path),
            "operation_id": op.id,
            "description": op.description,
        }

    def _match(self, content: str, pattern: str, case_sensitive: bool = True) -> int:
        """Semantic matching — first exact match, then context-tolerant match."""
        # 1. Exact match
        idx = content.find(pattern) if case_sensitive else content.lower().find(pattern.lower())
        if idx >= 0:
            return idx

        # 2. Fault-tolerant match — ignore leading/trailing whitespace differences
        stripped = pattern.strip()
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if stripped in line:
                # Restore position in content
                pos = sum(len(ln) + 1 for ln in lines[:i])
                return pos + line.find(stripped)

        return -1

    # ── Atomic Batch Edit ──

    def batch_edit(self, edits: list[DiffEdit], description: str = "", agent_id: str = "") -> dict:
        """Atomic multi-file edit — all succeed or all roll back.

        Steps:
          1. Dry-run validation on all files
          2. Execute edits one by one
          3. Any failure → roll back all
          4. All succeed → record as one atomic operation
        """
        if not edits:
            return {"success": False, "error": "no edits provided"}

        # Phase 1: Dry-run validation
        snapshots: list[tuple[str, str]] = []  # (path, original_content)
        prepared: list[tuple[int, DiffEdit, str]] = []  # (idx, edit, new_content)

        for i, edit in enumerate(edits):
            path = Path(edit.path)
            if not path.exists():
                return {
                    "success": False,
                    "error": f"file not found: {edit.path}",
                    "file": str(edit.path),
                    "edit_index": i,
                }

            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                return {
                    "success": False,
                    "error": f"read failed: {edit.path}: {e}",
                    "file": str(edit.path),
                    "edit_index": i,
                }

            snapshots.append((str(path), content))

            old = edit.old_str
            new = edit.new_str
            idx = self._match(content, old, edit.case_sensitive)
            if idx < 0:
                return {
                    "success": False,
                    "error": f"old_str not found: {edit.path}",
                    "file": str(edit.path),
                    "edit_index": i,
                }

            new_content = content[:idx] + new + content[idx + len(old) :]
            prepared.append((i, edit, new_content))

        # Phase 2: Execute edits
        applied: list[dict] = []
        try:
            for _i, edit, new_content in prepared:
                Path(edit.path).write_text(new_content, encoding="utf-8")
                applied.append(
                    {
                        "path": edit.path,
                        "old": edit.old_str,
                        "new": edit.new_str[:LOG_TRUNC_100],
                        "line": edit.start_line or 1,
                    }
                )
        except (OSError, ValueError) as e:
            # Phase 3: Roll back all
            for path_str, orig in snapshots:
                try:
                    Path(path_str).write_text(orig, encoding="utf-8")
                except OSError as re:
                    from l3.error_bus import capture

                    capture(
                        "batch_edit rollback failed", error_code="E_FILE_EDIT_ROLLBACK", component="file_editor", exc=re
                    )
                    logger.error("batch_edit rollback failed: %s: %s", path_str, re)
            return {
                "success": False,
                "error": f"write failed, all rolled back: {e}",
                "applied_before_rollback": len(applied),
            }

        # Record operation
        op = EditOperation(
            edits=applied,
            description=description or f"batch edit: {len(edits)} files",
            agent_id=agent_id,
        )
        self._push(op)

        return {
            "success": True,
            "operation_id": op.id,
            "files": len(applied),
            "edits": applied,
            "description": op.description,
        }

    # ── Undo / Redo ──

    def undo(self, operation_id: str = "") -> dict:
        """Rollback the most recent (or specified) operation."""
        with self._lock:
            if not self._history:
                return {"success": False, "error": "nothing to undo"}

            if operation_id:
                op = next((o for o in reversed(self._history) if o.id == operation_id), None)
            else:
                op = self._history[-1]

            if not op:
                return {"success": False, "error": f"operation not found: {operation_id}"}

        # Reverse order rollback
        for e in reversed(op.edits):
            path = Path(e["path"])
            if not path.exists():
                logger.warning("undo: file gone, skipping: %s", e["path"])
                continue
            try:
                content = path.read_text(encoding="utf-8")
                new_str = e["new"]
                old_str = e["old"]
                idx = self._match(content, new_str)
                if idx >= 0:
                    restored = content[:idx] + old_str + content[idx + len(new_str) :]
                    path.write_text(restored, encoding="utf-8")
                else:
                    logger.warning("undo: cannot find new_str to revert: %s", e["path"])
            except OSError as ex:
                return {"success": False, "error": f"undo failed: {e['path']}: {ex}"}

        with self._lock:
            self._history.remove(op)
            self._redo_stack.append(op)

        return {"success": True, "operation_id": op.id, "description": op.description, "type": "undo"}

    def redo(self) -> dict:
        """Redo the most recently undone operation."""
        with self._lock:
            if not self._redo_stack:
                return {"success": False, "error": "nothing to redo"}
            op = self._redo_stack.pop()

        # Redo all edits
        for e in op.edits:
            path = Path(e["path"])
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8")
                old_str = e["old"]
                new_str = e["new"]
                idx = self._match(content, old_str)
                if idx >= 0:
                    restored = content[:idx] + new_str + content[idx + len(old_str) :]
                    path.write_text(restored, encoding="utf-8")
            except OSError as ex:
                return {"success": False, "error": f"redo failed: {e['path']}: {ex}"}

        self._push(op)
        return {"success": True, "operation_id": op.id, "description": op.description, "type": "redo"}

    # ── History Query ──

    def history(self, limit: int = 50) -> dict:
        """Return recent edit operations with undo/redo availability."""
        with self._lock:
            entries = [o.to_dict() for o in self._history[-limit:]]
            entries.reverse()
            return {
                "success": True,
                "count": len(entries),
                "entries": entries,
                "undo_available": len(self._history),
                "redo_available": len(self._redo_stack),
            }

    # ── Internal ──

    def _push(self, op: EditOperation) -> None:
        with self._lock:
            self._history.append(op)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            self._redo_stack.clear()


# ── Global singleton ──

_engine: EditEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> EditEngine:
    """Return the shared EditEngine singleton, creating it on first use."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = EditEngine()
    return _engine


def reset_engine() -> None:
    """Reset the singleton (used by tests, conftest _RESETS)."""
    global _engine
    with _engine_lock:
        _engine = None
