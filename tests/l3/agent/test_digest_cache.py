"""Tests for the conversation digest cache (B1)."""

from __future__ import annotations

import time

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


def test_reclaim_sweeps_expired_digests():
    """reclaim physically drops expired digests (per-Cell sweep)."""
    from l3.memory.tiered_cache import get_tiered_cache, reset_tiered_cache

    reset_tiered_cache()
    reset_digest()
    try:
        set_digest_switches(enabled=True)
        fold_messages("cell-A", "card-1", [{"role": "user", "content": "x"}])
        # Force expiry: rewrite the stored timestamp into the past.
        cache = get_tiered_cache()
        for key in cache.keys("L2"):
            value, _ts = cache._layers["L2"][key]
            cache._layers["L2"][key] = (value, time.time() - 9999)
        assert reclaim("cell-A") == 1
        assert cache.keys("L2") == []
    finally:
        reset_digest()
        reset_tiered_cache()


def test_reclaim_keeps_fresh_digests():
    """reclaim leaves non-expired digests untouched."""
    from l3.memory.tiered_cache import reset_tiered_cache

    reset_tiered_cache()
    reset_digest()
    try:
        set_digest_switches(enabled=True)
        fold_messages("cell-B", "card-2", [{"role": "user", "content": "y"}])
        assert reclaim("cell-B") == 0
        assert get_digest("cell-B", "card-2") != ""
    finally:
        reset_digest()
        reset_tiered_cache()
