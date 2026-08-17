"""WS5.5: fs_adapter routes file ops through the VFS mount table."""
from __future__ import annotations

import pytest

from l1.kernel.vfs import MountType, get_vfs, reset_vfs
from l3.services.fs_adapter import FsAdapter


@pytest.fixture(autouse=True)
def _clean_vfs():
    reset_vfs()
    yield
    reset_vfs()


def _mount(tmp_path, name: str = "/proj", read_only: bool = False):
    root = tmp_path / "mount_root"
    root.mkdir(exist_ok=True)
    get_vfs().mount(name, MountType.PROJECT, real_path=str(root), min_ring=1, read_only=read_only)
    return root


def test_read_through_mount(tmp_path):
    """A path under a mount resolves through the mount mapping."""
    root = _mount(tmp_path)
    (root / "hello.txt").write_text("vfs wired", encoding="utf-8")
    r = FsAdapter().read("/proj/hello.txt")
    assert r["success"], r
    assert r["content"] == "vfs wired"


def test_write_readonly_mount_denied(tmp_path):
    """Writes to a read-only mount are refused (EROFS)."""
    root = _mount(tmp_path, read_only=True)
    r = FsAdapter().write("/proj/new.txt", "x")
    assert not r["success"]
    assert "EROFS" in r["error"]
    assert not (root / "new.txt").exists()


def test_write_through_mount(tmp_path):
    """Writes under a writable mount land in the mount real path."""
    root = _mount(tmp_path)
    r = FsAdapter().write("/proj/data.txt", "hello")
    assert r["success"], r
    assert (root / "data.txt").read_text(encoding="utf-8") == "hello"


def test_unmounted_path_direct_access(tmp_path):
    """Paths outside any mount keep direct OS access."""
    f = tmp_path / "plain.txt"
    f.write_text("direct", encoding="utf-8")
    r = FsAdapter().read(str(f))
    assert r["success"], r
    assert r["content"] == "direct"


def test_traversal_blocked(tmp_path, tmp_path_factory):
    """A path escaping the mount root through .. is refused."""
    root = _mount(tmp_path)
    secret = root.parent / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    r = FsAdapter().read("/proj/../secret.txt")
    assert not r["success"]
    assert "EACCES" in r["error"]


def test_list_tree_through_mount(tmp_path):
    """list_tree under a mount maps to the mount real path."""
    root = _mount(tmp_path)
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "b.txt").write_text("b", encoding="utf-8")
    r = FsAdapter().list_tree("/proj")
    assert r["success"], r
    assert r["count"] == 3, f"got {r['count']}: {[e['path'] for e in r.get('entries', [])]}"
