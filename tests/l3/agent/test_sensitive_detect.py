"""Tests for sensitive-info bypass detection (B6)."""

from __future__ import annotations

from l3.agent.sensitive_detect import reset_sensitive, scan_text, sensitive_status, set_sensitive_switches


def test_enabled_by_default():
    reset_sensitive()
    try:
        assert sensitive_status()["enabled"] is True
    finally:
        reset_sensitive()


def test_scans_api_key_and_ip():
    reset_sensitive()
    try:
        hits = scan_text("key sk-abcdefghijklmnopqrstuvwxyz at 1.2.3.4")
        kinds = {h["kind"] for h in hits}
        assert "api_key" in kinds
        assert "ipv4" in kinds
    finally:
        reset_sensitive()


def test_disabled_returns_empty():
    reset_sensitive()
    try:
        set_sensitive_switches(enabled=False)
        assert scan_text("sk-abcdefghijklmnopqrstuvwxyz") == []
    finally:
        reset_sensitive()
