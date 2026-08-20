"""Verify stable Python VFS mount-resolution values from the shared fixture."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.vfs import VFS, MountType

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_vfs_vectors.json"


def test_vfs_mount_resolution_vectors_match_python_reference():
    """Keep longest-prefix resolution and unmounted behavior language-neutral."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    for vector in vectors:
        vfs = VFS()
        for mount in vector["mounts"]:
            vfs.mount(
                mount["name"],
                MountType[mount["mount_type"]],
                real_path=mount["real_path"],
                min_ring=mount["min_ring"],
                read_only=mount["read_only"],
            )
        assert vfs.resolve_mount(vector["path"]) == vector["expect"]
