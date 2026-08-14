"""Tests for the conversation digest cache (B1)."""

from __future__ import annotations

from l3.agent.digest_cache import (
    digest_status,
    fold_messages,
    get_digest,
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
