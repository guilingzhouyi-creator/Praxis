"""Validate shared platform command and endpoint vectors against Python."""

from __future__ import annotations

import json
from pathlib import Path

import l1.kernel.platform as platform

_VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "kernel_platform_vectors.json"


def test_shared_platform_vectors_match_python_reference(monkeypatch) -> None:
    """Keep Rust platform values aligned with the Python reference helpers."""
    vectors = json.loads(_VECTORS.read_text(encoding="utf-8"))
    original_windows = platform.IS_WINDOWS
    original_shell = platform.SHELL_PATH
    try:
        for vector in vectors:
            snapshot = vector["snapshot"]
            monkeypatch.setattr(platform, "IS_WINDOWS", snapshot["is_windows"])
            monkeypatch.setattr(platform, "SHELL_PATH", snapshot["shell_path"])
            monkeypatch.setattr(
                platform,
                "which",
                lambda name, available=snapshot["rg_available"]: "/usr/bin/rg" if available and name == "rg" else None,
            )
            assert platform.shell_command("echo ready") == vector["shell_command"]
            options = vector["grep_options"]
            assert platform.grep_cmd(**options) == vector["grep_command"]
            assert platform.join_url(*vector["url_parts"]) == vector["url"]
            assert platform._parse_tcp_endpoint(vector["tcp_endpoint"], vector["tcp_default_host"]) == (
                vector["tcp"][0],
                vector["tcp"][1],
            )
    finally:
        monkeypatch.setattr(platform, "IS_WINDOWS", original_windows)
        monkeypatch.setattr(platform, "SHELL_PATH", original_shell)
