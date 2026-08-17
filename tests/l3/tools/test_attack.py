"""Tests for the attack-posture tool suite (recon / scan / fetch).

Covers the posture gate: default productive posture denies every attack
tool; security-test posture allows calls only against whitelisted targets
in an offensive domain. Evidence is recorded on both paths.
"""

from __future__ import annotations

import socket

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


def test_whitelisted_target_allowed_in_attack_posture(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(socket.AF_INET, 0, 0, "", ("192.0.2.10", 0))])
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


def test_attack_requires_full_power_confirmation(monkeypatch):
    """Attack classification alone cannot invoke the offensive tool suite."""
    import l3.tool_system.security_mode as security_mode

    reset_posture_matrix()
    reset_security_mode()
    try:
        get_posture_matrix().set_domain("red", offensive=True, target_whitelist=["example.com"])
        monkeypatch.setattr(security_mode, "get_security_mode", lambda: "security-test")
        monkeypatch.setattr(security_mode, "get_posture", lambda: {"full_power": False})
        result = dns_lookup({"host": "example.com", "domain": "red"}, "tester")
        assert result["success"] is False
        assert "full_power" in result["error"]
    finally:
        reset_security_mode()
        reset_posture_matrix()


def test_allowed_attack_result_and_denial_are_both_evidence(monkeypatch, tmp_path):
    """Allowed execution records its result while posture denial remains auditable."""
    from l3.tool_system.security_evidence import get_evidence, reset_evidence

    monkeypatch.setenv("PRAXIS_SECURITY_EVIDENCE_PATH", str(tmp_path / "attack.jsonl"))
    reset_evidence()
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(socket.AF_INET, 0, 0, "", ("192.0.2.10", 0))])
    reset_posture_matrix()
    reset_security_mode()
    try:
        get_posture_matrix().set_domain("red", offensive=True, target_whitelist=["example.com"])
        set_security_mode("security-test", confirmed=True, source="test")
        allowed = dns_lookup({"host": "example.com", "domain": "red"}, "tester")
        assert allowed["success"] is True
        denied = dns_lookup({"host": "blocked.example", "domain": "red"}, "tester")
        assert denied["success"] is False
        rows = get_evidence().query_evidence(phase="attack_tool")
        assert any(row["decision"] == "ALLOW" and row["raw"]["result"]["success"] for row in rows)
        assert any(row["decision"] == "BLOCK" for row in rows)
    finally:
        reset_security_mode()
        reset_posture_matrix()
        reset_evidence()


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
