"""Tests for the conversation digest cache (B1)."""

from __future__ import annotations

from l3.agent.digest_cache import (
    digest_status,
    fold_messages,
    get_digest,
    reclaim,
    reset_digest,
    set_digest_switches,
)


def test_disabled_by_default():
    reset_digest()
    try:
        assert digest_status()["enabled"] is False
        msgs = [{"role": "user", "content": "第一步：分析"}]
        assert fold_messages("cell-A", "card-1", msgs) == ""
    finally:
        reset_digest()


def test_enabled_fold_and_recover():
    reset_digest()
    try:
        set_digest_switches(enabled=True)
        msgs = [
            {"role": "user", "content": "第一步：分析仓库"},
            {"role": "assistant", "content": "扫描中"},
            {"role": "user", "content": "第二步：生成报告"},
        ]
        digest = fold_messages("cell-A", "card-42", msgs)
        assert digest.startswith("[FOLDED]")
        assert get_digest("cell-A", "card-42") == digest
    finally:
        reset_digest()


def test_disabled_after_enable_returns_empty():
    reset_digest()
    try:
        set_digest_switches(enabled=True)
        msgs = [{"role": "user", "content": "x"}]
        fold_messages("cell-A", "card-1", msgs)
        set_digest_switches(enabled=False)
        assert fold_messages("cell-A", "card-1", msgs) == ""
    finally:
        reset_digest()


def test_reclaim_clears_cell_digests():
    """reclaim drops this Cell's digests (physical delete, teardown)."""
    from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache

    reset_tiered_cache()
    reset_digest()
    try:
        set_digest_switches(enabled=True)
        fold_messages("cell-A", "card-1", [{"role": "user", "content": "x"}])
        fold_messages("cell-A", "card-2", [{"role": "user", "content": "y"}])
        assert reclaim("cell-A") == 2
        assert get_tiered_cache().keys("L2") == []
    finally:
        reset_digest()
        reset_tiered_cache()


def test_reclaim_isolates_other_cell():
    """reclaim(cell-A) leaves cell-B's digests untouched."""
    from l3.memory.tiered_cache import reset_tiered_cache

    reset_tiered_cache()
    reset_digest()
    try:
        set_digest_switches(enabled=True)
        fold_messages("cell-A", "card-1", [{"role": "user", "content": "x"}])
        fold_messages("cell-B", "card-2", [{"role": "user", "content": "y"}])
        assert reclaim("cell-A") == 1
        assert get_digest("cell-B", "card-2") != ""
    finally:
        reset_digest()
        reset_tiered_cache()
