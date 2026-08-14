"""Tests for the global shared prompt library (3.2, P0-③)."""

from __future__ import annotations

from l3.agent.global_prompt_library import (
    global_prompt_library_status,
    list_sub_libraries,
    register_sub_library,
    reset_global_prompt_library,
    resolve_global_prompt,
    set_global_prompt_library_switches,
)


def _seed():
    register_sub_library("security", "SECURITY TEXT")
    register_sub_library("performance", "PERFORMANCE TEXT")
    register_sub_library("extension", "EXTENSION TEXT")


def test_enabled_by_default():
    reset_global_prompt_library()
    try:
        assert global_prompt_library_status()["enabled"] is True
    finally:
        reset_global_prompt_library()


def test_low_load_returns_extension_baseline():
    reset_global_prompt_library()
    try:
        _seed()
        text = resolve_global_prompt(load=0.2, domain="build")
        assert "EXTENSION TEXT" in text
        assert "PERFORMANCE TEXT" not in text
    finally:
        reset_global_prompt_library()


def test_high_load_adds_performance():
    reset_global_prompt_library()
    try:
        _seed()
        text = resolve_global_prompt(load=0.9, domain="build")
        assert "PERFORMANCE TEXT" in text
    finally:
        reset_global_prompt_library()


def test_security_domain_adds_security_sub_library():
    reset_global_prompt_library()
    try:
        _seed()
        text = resolve_global_prompt(load=0.3, domain="security")
        assert "SECURITY TEXT" in text
    finally:
        reset_global_prompt_library()


def test_disabled_returns_empty():
    reset_global_prompt_library()
    try:
        _seed()
        set_global_prompt_library_switches(enabled=False)
        assert resolve_global_prompt(load=0.9, domain="security") == ""
    finally:
        reset_global_prompt_library()


def test_user_register_rejected_system_managed():
    """Only system callers may register sub-libraries (user edits forbidden)."""
    reset_global_prompt_library()
    try:
        assert register_sub_library("userlib", "X", source="user") is False
        assert "userlib" not in list_sub_libraries()
        assert register_sub_library("syslib", "Y", source="system") is True
        assert "syslib" in list_sub_libraries()
    finally:
        reset_global_prompt_library()
