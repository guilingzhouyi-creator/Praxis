"""Tests for the TS-friendly storage/lock ports (P2-⑤)."""

from __future__ import annotations


def test_fs_storage_read_write_roundtrip(tmp_path):
    """P2-⑤: StoragePort read/write round-trips through the FS adapter."""
    from l1.kernel.ports.storage import FsStoragePort

    store = FsStoragePort()
    p = str(tmp_path / "sub" / "f.json")
    store.write_text(p, '{"a": 1}')
    assert store.read_text(p) == '{"a": 1}'
    assert store.exists(p) is True


def test_fs_storage_missing_file_returns_empty(tmp_path):
    from l1.kernel.ports.storage import FsStoragePort

    store = FsStoragePort()
    assert store.read_text(str(tmp_path / "missing.json")) == ""
    assert store.exists(str(tmp_path / "missing.json")) is False


def test_fs_storage_list_json(tmp_path):
    from l1.kernel.ports.storage import FsStoragePort

    store = FsStoragePort()
    (tmp_path / "a_tools.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b_thoughts.json").write_text("{}", encoding="utf-8")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    files = store.list_json(str(tmp_path / "*_*.json"))
    assert len(files) == 2
    assert all(f.endswith(".json") for f in files)


def test_get_storage_default_and_reset():
    """P2-⑤: get_storage returns the FS adapter; set/reset swaps it."""
    from l1.kernel.ports.storage import FsStoragePort, get_storage, reset_storage, set_storage

    reset_storage()
    try:
        assert isinstance(get_storage(), FsStoragePort)
        set_storage(FsStoragePort())
        assert isinstance(get_storage(), FsStoragePort)
    finally:
        reset_storage()


def test_thread_lock_port_context():
    """P2-⑤: LockPort works as a context manager (mutex scope)."""
    from l1.kernel.ports.lock import new_lock

    lock = new_lock()
    with lock:
        assert lock is not None  # acquired/released within the scope
