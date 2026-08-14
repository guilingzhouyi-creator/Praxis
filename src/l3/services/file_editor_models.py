"""File editor — core data models.

Extracted from ``file_editor.py``: DiffEdit (semantic edit operation),
EditOperation (history record) and Patch (serializable patch) — pure
dataclasses with no engine logic, shared by EditEngine and PatchManager.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

from l1.kernel.params.system import HASH_TRUNC_MEDIUM, LOG_TRUNC_100


@dataclass
class DiffEdit:
    """Single semantic edit operation.

    old_str: Original text to replace (supports context-tolerant matching)
    new_str: Replacement text
    path:    File path
    description: Human-readable edit description
    """

    path: str
    old_str: str
    new_str: str
    description: str = ""
    start_line: int = 0  # Exact line number (optional)
    end_line: int = 0
    case_sensitive: bool = True

    def to_dict(self) -> dict:
        """Serialize the edit to a dict."""
        return {
            "path": self.path,
            "old_str": self.old_str[:LOG_TRUNC_100],
            "new_str": self.new_str[:LOG_TRUNC_100],
            "description": self.description,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass
class EditOperation:
    """A single executed edit operation (used for history stack)."""

    id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:HASH_TRUNC_MEDIUM])
    timestamp: float = field(default_factory=time.time)
    edits: list[dict] = field(default_factory=list)  # [{"path", "old", "new", "line"}, ...]
    description: str = ""
    agent_id: str = ""
    success: bool = True

    def to_dict(self) -> dict:
        """Serialize the edit operation to a dict."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "edits": self.edits,
            "description": self.description,
            "agent_id": self.agent_id,
            "success": self.success,
        }


@dataclass
class Patch:
    """Structured patch, serializable to file."""

    id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:HASH_TRUNC_MEDIUM])
    created_at: float = field(default_factory=time.time)
    description: str = ""
    author: str = ""
    changes: list[dict] = field(default_factory=list)  # [{"path", "old", "new", "line"}, ...]
    applied: bool = False
    reverted: bool = False

    def to_dict(self) -> dict:
        """Serialize the patch to a dict."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "description": self.description,
            "author": self.author,
            "changes": self.changes,
            "applied": self.applied,
            "reverted": self.reverted,
        }

    def to_json(self) -> str:
        """Serialize the patch to a JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Patch:
        """Rebuild a patch from a JSON string, ignoring unknown keys."""
        data = json.loads(raw)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
