"""Tests for the recursive-compression threshold + circuit breaker (B6)."""

from __future__ import annotations

from l3.agent.compression_guard import (
    check_recursion,
    guard_status,
    record_compress_pass,
    reset_guard,
    set_guard_switches,
)


def test_defaults_threshold_off_breaker_on():
    reset_guard()
    try:
        st = guard_status()
        assert st["recursion_threshold"] == 0
        assert st["breaker_enabled"] is True
        assert st["tripped"] is False
    finally:
        reset_guard()


def test_threshold_blocks_and_trips_breaker():
    reset_guard()
    try:
        set_guard_switches(recursion_threshold=2)
        # Pass 1: depth 0 < threshold → allowed.
        assert check_recursion("s1")["blocked"] is False
        record_compress_pass("s1")
        # Pass 2: depth 1 < threshold → allowed.
        assert check_recursion("s1")["blocked"] is False
        record_compress_pass("s1")
        # Pass 3: depth 2 >= threshold → blocked + breaker trips.
        r = check_recursion("s1")
        assert r["blocked"] is True
        assert "threshold" in r["error"]
        assert guard_status()["tripped"] is True
    finally:
        reset_guard()


def test_setting_threshold_resets_tripped_breaker():
    reset_guard()
    try:
        set_guard_switches(recursion_threshold=1)
        record_compress_pass("s2")
        check_recursion("s2")
        assert guard_status()["tripped"] is True
        set_guard_switches(recursion_threshold=3)
        assert guard_status()["tripped"] is False
    finally:
        reset_guard()
