"""Tests for memory injection dedup (inject-dedup)."""

from __future__ import annotations

from l3.memory.memory_context import (
    _dedup_block,
    inject_dedup_status,
    reset_inject_dedup,
    set_inject_dedup,
)


def _reset():
    reset_inject_dedup()


def test_default_enabled():
    _reset()
    try:
        assert inject_dedup_status()["enabled"] is True
    finally:
        _reset()


def test_dedup_drops_repeated_lines():
    _reset()
    try:
        text = "line one\nline two\nline one\nline three\nline two"
        out = _dedup_block(text)
        assert out.count("line one") == 1
        assert out.count("line two") == 1
        assert out.count("line three") == 1
    finally:
        _reset()


def test_dedup_keeps_watermarks():
    _reset()
    try:
        text = "<!-- WATERMARK: id=abc -->\ncontent\n<!-- WATERMARK: id=def -->\ncontent"
        out = _dedup_block(text)
        assert out.count("<!-- WATERMARK:") == 2, "watermark lines must not dedup"
        assert out.count("content") == 1
    finally:
        _reset()


def test_disabled_returns_input_unchanged():
    _reset()
    try:
        set_inject_dedup(False)
        text = "a\na\na"
        assert _dedup_block(text) == text
    finally:
        _reset()


def test_empty_input():
    _reset()
    try:
        assert _dedup_block("") == ""
    finally:
        _reset()
