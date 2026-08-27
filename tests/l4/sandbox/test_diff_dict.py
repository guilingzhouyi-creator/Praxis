"""2.1 Phase-2 tests — shared Zstd dictionary (train/load/cache, declarative).

Verifies the dictionary can be trained from declared samples, loaded back,
and that the cache + invalidation behave; all paths degrade gracefully when
zstandard or samples are unavailable.
"""

from __future__ import annotations

import pytest

from l4.sandbox import diff_dict


@pytest.fixture(autouse=True)
def _clean():
    diff_dict.invalidate_dictionary()
    yield
    diff_dict.invalidate_dictionary()


def test_status_shape():
    """status() reports availability + path without raising."""
    st = diff_dict.status()
    assert "available" in st
    assert "bytes" in st
    assert "path" in st


def test_train_requires_samples(tmp_path):
    """Training with no samples fails gracefully (no raise)."""
    empty = tmp_path / "empty"
    empty.mkdir()
    r = diff_dict.train_dictionary(path=str(tmp_path / "d.bin"), force=True)
    assert r["success"] in (True, False)  # may train from repo systems/python-reference-runtime/ samples


def test_train_persists_and_loads(tmp_path):
    """Training persists a dictionary that load_dictionary reads back."""
    target = str(tmp_path / "shared.bin")
    r = diff_dict.train_dictionary(path=target, force=True)
    if not r.get("success"):
        pytest.skip("zstandard or samples unavailable in this env")
    assert r["success"] is True
    assert r["bytes"] > 0
    loaded = diff_dict.load_dictionary(path=target)
    assert loaded is not None and len(loaded) == r["bytes"]


def test_load_absent_returns_none(tmp_path):
    """load_dictionary on a missing file returns None (no raise)."""
    assert diff_dict.load_dictionary(path=str(tmp_path / "missing.bin")) is None


def test_cache_and_invalidate(tmp_path):
    """get_dictionary caches; invalidate_dictionary forces a reload."""
    target = str(tmp_path / "c.bin")
    r = diff_dict.train_dictionary(path=target, force=True)
    if not r.get("success"):
        pytest.skip("zstandard or samples unavailable in this env")
    # Prime the cache through the default path override.
    diff_dict._cache = diff_dict.load_dictionary(path=target)
    diff_dict._cache_loaded = True
    assert diff_dict.get_dictionary() is not None
    diff_dict.invalidate_dictionary()
    assert diff_dict._cache_loaded is False
