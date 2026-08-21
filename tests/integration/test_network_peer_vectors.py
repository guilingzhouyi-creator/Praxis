"""Cross-language lifecycle vectors for the Python3 network adapter."""

from __future__ import annotations

import json
from pathlib import Path

from l1.kernel.net import NetKernel
from l1.kernel.ports import Endpoint, TransportPort
from l1.kernel.ports import Result as PortResult


class _NoopTransport(TransportPort):
    """Keep peer bookkeeping tests independent from sockets."""

    name = "noop"

    def start(self, node_id: str, config) -> PortResult:
        return PortResult.ok(node_id=node_id)

    def stop(self) -> PortResult:
        return PortResult.ok(stopped=True)

    def send(self, target: Endpoint, data: bytes) -> PortResult:
        return PortResult.ok(target=target.address, bytes=len(data))

    def register_handler(self, msg_type: str, handler) -> None:
        return None


def test_shared_peer_vectors_match_python_adapter(monkeypatch):
    """Keep timeout, loss-once, and eviction lifecycle aligned with Rust."""
    vectors = json.loads(Path("tests/fixtures/kernel_peer_vectors.json").read_text(encoding="utf-8"))
    network_module = __import__("l1.kernel.net", fromlist=["time"])
    kernel = NetKernel(transport=_NoopTransport())
    kernel._node_id = vectors["self_id"]

    for operation in vectors["operations"]:
        at_seconds = operation["at_ms"] / 1000
        monkeypatch.setattr(network_module.time, "time", lambda at_seconds=at_seconds: at_seconds)
        if operation["kind"] == "announce":
            kernel._on_peer_announce(
                {
                    "peer_id": operation["peer_id"],
                    "host": operation["host"],
                    "port": operation["port"],
                    "cells": operation["cells"],
                    "version": operation["version"],
                }
            )
        elif operation["kind"] == "health":
            health = kernel.health()
            assert health["status"] == operation["status"]
            assert health["peers_total"] == operation["peers_total"]
            assert health["peers_alive"] == operation["peers_alive"]
            assert health["peers_dead"] == operation["peers_dead"]
            for peer_id in operation["lost"]:
                assert kernel._peers[peer_id]._loss_reported is True
            for peer_id in operation["evicted"]:
                assert peer_id not in kernel._peers
        else:
            raise AssertionError(f"unknown peer operation: {operation['kind']}")

    assert sorted(kernel._peers) == vectors["expected_peer_ids"]
