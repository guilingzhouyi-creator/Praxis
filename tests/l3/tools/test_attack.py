"""Tests for the attack-posture tool suite (recon / scan / fetch).

Covers the posture gate: default productive posture denies every attack
tool; security-test posture allows calls only against whitelisted targets
in an offensive domain. Evidence is recorded on both paths.
"""

from __future__ import annotations

from l3.tool_system.posture_matrix import get_posture_matrix, reset_posture_matrix
from l3.tool_system.security_mode import reset_security_mode, set_security_mode
from l3.tools._attack import dns_lookup, http_probe, tcp_scan, url_fetch


def test_productive_posture_denies_all():
    for fn, args in [
        (http_probe, {"url": "http://example.com"}),
        (tcp_scan, {"host": "example.com", "ports": "80,443"}),
        (dns_lookup, {"host": "example.com"}),
        (url_fetch, {"url": "http://example.com"}),
    ]:
        r = fn(args, "tester")
        assert r["success"] is False
        assert "security-test" in r["error"]


def test_whitelisted_target_allowed_in_attack_posture():
    reset_posture_matrix()
    reset_security_mode()
    try:
        get_posture_matrix().set_domain("red", offensive=True, target_whitelist=["example.com"])
        set_security_mode("security-test", confirmed=True, source="test")
        r = dns_lookup({"host": "example.com", "domain": "red"}, "tester")
        assert r["success"] is True
        assert "addresses" in r
    finally:
        reset_security_mode()
        reset_posture_matrix()


def test_non_whitelisted_target_denied():
    reset_posture_matrix()
    reset_security_mode()
    try:
        get_posture_matrix().set_domain("red", offensive=True, target_whitelist=["example.com"])
        set_security_mode("security-test", confirmed=True, source="test")
        r = dns_lookup({"host": "evil.org", "domain": "red"}, "tester")
        assert r["success"] is False
        assert "whitelist" in r["error"]
    finally:
        reset_security_mode()
        reset_posture_matrix()


def test_non_offensive_domain_denied():
    reset_posture_matrix()
    reset_security_mode()
    try:
        get_posture_matrix().set_domain("red", offensive=True, target_whitelist=["example.com"])
        set_security_mode("security-test", confirmed=True, source="test")
        r = http_probe({"url": "http://example.com", "domain": "blue"}, "tester")
        assert r["success"] is False
        assert "offensive posture" in r["error"]
    finally:
        reset_security_mode()
        reset_posture_matrix()


def test_http_probe_requires_http_scheme():
    reset_posture_matrix()
    reset_security_mode()
    try:
        get_posture_matrix().set_domain("red", offensive=True, target_whitelist=["*"])
        set_security_mode("security-test", confirmed=True, source="test")
        r = http_probe({"url": "ftp://example.com", "domain": "red"}, "tester")
        assert r["success"] is False
        assert "http(s)" in r["error"]
    finally:
        reset_security_mode()
        reset_posture_matrix()
