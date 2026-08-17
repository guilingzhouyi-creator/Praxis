"""Attack-posture tool suite — recon / scan / fetch for security-test mode.

These tools are ONLY callable under the ``security-test`` (attack) posture
and only against targets in the offensive domain's whitelist; in the default
``productive`` posture every tool here is rejected with a posture-gate error.
Every call (allow or deny) is recorded on the security-evidence chain, so an
attack session is fully auditable. The safety bottom line (constitution,
gatechain, sandbox, reference-channel recording) still applies on top —
attack posture widens the toolset, it never weakens the pipeline gates.

Tools:
  - http_probe:  HTTP(S) HEAD/GET probe with timeout (recon).
  - tcp_scan:    TCP connect-scan of a host:port list (scan).
  - dns_lookup:  DNS resolution of a host (recon).
  - url_fetch:   Fetch a URL body with size cap (fetch).
"""

from __future__ import annotations

import functools
import logging
import socket
import time

from l1.kernel.params.system import (
    SECURITY_MODE_TEST,
)
from l1.kernel.params.tool import (
    ATTACK_FETCH_MAX_BYTES,
    ATTACK_PROBE_TIMEOUT,
    ATTACK_SCAN_MAX_PORTS,
)

logger = logging.getLogger(__name__)


def _measure_attack(tool_name: str):
    """Decorate one attack tool with duration and outcome metrics."""

    def decorate(fn):
        @functools.wraps(fn)
        def measured(args: dict, agent_id: str) -> dict:
            started = time.perf_counter()
            result: dict = {}
            try:
                result = fn(args, agent_id)
                return result
            finally:
                from l3.services.observability import emit_count, emit_duration

                tags = {"tool": tool_name, "agent": agent_id, "success": result.get("success", False)}
                emit_duration("attack_tool.duration_ms", started, tags=tags)
                emit_count("attack_tool.count", tags=tags)

        return measured

    return decorate


def _record_attack_result(tool: str, target: str, domain: str, result: dict) -> dict:
    """Record an allowed attack-tool invocation and return its result."""
    try:
        from l3.tool_system.security_evidence import DECISION_ALLOW, record_evidence

        record_evidence(
            phase="attack_tool",
            gate="execution",
            decision=DECISION_ALLOW,
            target=target,
            source=tool,
            tags={"domain": domain, "success": str(bool(result.get("success"))).lower()},
            raw={"tool": tool, "result": result},
        )
    except Exception:
        logger.debug("attack tool evidence skipped", exc_info=True)
    return result


def _posture_gate(domain: str, target: str) -> dict | None:
    """Reject unless security-test posture + offensive domain + whitelisted target.

    Args:
        domain: offensive domain owning the call (target whitelist scope).
        target: host or URL being probed.

    Returns:
        An error dict when the call is not permitted, else None.
    """
    from l3.tool_system.posture_matrix import get_posture_matrix
    from l3.tool_system.security_evidence import DECISION_BLOCK, record_evidence
    from l3.tool_system.security_mode import get_posture, get_security_mode

    mode = get_security_mode()
    matrix = get_posture_matrix()
    error = ""
    if mode != SECURITY_MODE_TEST:
        error = "attack tools require security-test posture (productive denies them)"
    elif not matrix.is_offensive(domain):
        error = f"attack tools require offensive posture for domain '{domain}'"
    elif not get_posture().get("full_power", False):
        error = "attack tools require explicit full_power confirmation"
    elif not matrix.target_allowed(domain, target):
        error = f"target '{target}' is not in domain '{domain}' whitelist"
    if error:
        from contextlib import suppress

        with suppress(Exception):
            record_evidence(
                phase="attack_tool",
                gate="posture_gate",
                decision=DECISION_BLOCK,
                target=target,
                source="attack_tool",
                tags={"domain": domain, "mode": mode},
            )
        return {"success": False, "error": error}
    return None


@_measure_attack("http_probe")
def http_probe(args: dict, agent_id: str) -> dict:
    """Probe an HTTP(S) URL with a HEAD/GET request and short timeout."""
    import urllib.request

    url = str(args.get("url", "") or "")
    method = str(args.get("method", "HEAD")).upper()
    domain = str(args.get("domain", "") or "")
    blocked = _posture_gate(domain, url)
    if blocked:
        return blocked
    if not url.startswith(("http://", "https://")):
        return _record_attack_result("http_probe", url, domain, {"success": False, "error": "url must be http(s)://"})
    try:
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "praxis-attack/1.0"})
        with urllib.request.urlopen(req, timeout=ATTACK_PROBE_TIMEOUT) as resp:  # noqa: S310 - posture-gated
            return _record_attack_result(
                "http_probe", url, domain, {"success": True, "status": resp.status, "url": url, "method": method}
            )
    except Exception as e:
        return _record_attack_result(
            "http_probe", url, domain, {"success": False, "error": f"probe failed: {e}", "url": url}
        )


@_measure_attack("tcp_scan")
def tcp_scan(args: dict, agent_id: str) -> dict:
    """TCP connect-scan a host across a bounded port list."""
    host = str(args.get("host", "") or "")
    ports = args.get("ports") or []
    domain = str(args.get("domain", "") or "")
    blocked = _posture_gate(domain, host)
    if blocked:
        return blocked
    if isinstance(ports, str):
        try:
            ports = [int(p) for p in ports.replace(" ", "").split(",") if p.strip()]
        except ValueError:
            return _record_attack_result("tcp_scan", host, domain, {"success": False, "error": "invalid ports"})
    ports = [int(p) for p in ports if str(p).isdigit()][:ATTACK_SCAN_MAX_PORTS]
    if not ports:
        return _record_attack_result(
            "tcp_scan", host, domain, {"success": False, "error": "ports required (comma-separated)"}
        )
    open_ports: list[int] = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(ATTACK_PROBE_TIMEOUT)
            if s.connect_ex((host, port)) == 0:
                open_ports.append(port)
    return _record_attack_result(
        "tcp_scan", host, domain, {"success": True, "host": host, "open_ports": open_ports, "scanned": len(ports)}
    )


@_measure_attack("dns_lookup")
def dns_lookup(args: dict, agent_id: str) -> dict:
    """Resolve a hostname to its A/AAAA records (recon)."""
    host = str(args.get("host", "") or "")
    domain = str(args.get("domain", "") or "")
    blocked = _posture_gate(domain, host)
    if blocked:
        return blocked
    try:
        infos = socket.getaddrinfo(host, None)  # noqa: S105 - posture-gated
        addrs = sorted({info[4][0] for info in infos})
        return _record_attack_result("dns_lookup", host, domain, {"success": True, "host": host, "addresses": addrs})
    except Exception as e:
        return _record_attack_result(
            "dns_lookup", host, domain, {"success": False, "error": f"dns lookup failed: {e}", "host": host}
        )


@_measure_attack("url_fetch")
def url_fetch(args: dict, agent_id: str) -> dict:
    """Fetch a URL body with a hard size cap (fetch)."""
    import urllib.request

    url = str(args.get("url", "") or "")
    domain = str(args.get("domain", "") or "")
    blocked = _posture_gate(domain, url)
    if blocked:
        return blocked
    if not url.startswith(("http://", "https://")):
        return _record_attack_result("url_fetch", url, domain, {"success": False, "error": "url must be http(s)://"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "praxis-attack/1.0"})
        with urllib.request.urlopen(req, timeout=ATTACK_PROBE_TIMEOUT) as resp:  # noqa: S310 - posture-gated
            body = resp.read(ATTACK_FETCH_MAX_BYTES + 1)
            truncated = len(body) > ATTACK_FETCH_MAX_BYTES
            return _record_attack_result(
                "url_fetch",
                url,
                domain,
                {
                    "success": True,
                    "status": resp.status,
                    "url": url,
                    "body": body[:ATTACK_FETCH_MAX_BYTES].decode("utf-8", errors="replace"),
                    "truncated": truncated,
                },
            )
    except Exception as e:
        return _record_attack_result(
            "url_fetch", url, domain, {"success": False, "error": f"fetch failed: {e}", "url": url}
        )
