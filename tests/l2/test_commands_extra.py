"""Commands extra tests — covers the domain-split extra_* submodules."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "systems/python-reference-runtime"))


class TestCommandsExtra:
    def test_importable(self):
        import l2.l2_shell.commands.extra as e

        assert e is not None

    def test_has_cmd_think(self):
        from l2.l2_shell.commands.extra import _cmd_think

        assert callable(_cmd_think)

    # ── Domain submodules expose the same callables as the facade ──

    def test_facade_reexports_all_commands(self):
        from l2.l2_shell.commands import extra as facade
        from l2.l2_shell.commands.extra_cluster import _cmd_cells, _cmd_cluster, _cmd_cross, _cmd_htn
        from l2.l2_shell.commands.extra_mcp import _cmd_mcp
        from l2.l2_shell.commands.extra_resources import _cmd_buffer, _cmd_think
        from l2.l2_shell.commands.extra_security import _cmd_security
        from l2.l2_shell.commands.extra_stats import _cmd_stats

        for fn in (
            _cmd_cells,
            _cmd_cluster,
            _cmd_cross,
            _cmd_htn,
            _cmd_mcp,
            _cmd_buffer,
            _cmd_think,
            _cmd_security,
            _cmd_stats,
        ):
            assert getattr(facade, fn.__name__) is fn, f"{fn.__name__} not re-exported by facade"

    # ── extra_cluster ──

    def test_cmd_cluster_no_args(self):
        from l2.l2_shell.commands.extra_cluster import _cmd_cluster

        r = _cmd_cluster([])
        assert r.get("success") is True
        assert r.get("data", {}).get("state") == "single"

    def test_cmd_cluster_unknown_subcommand(self):
        from l2.l2_shell.commands.extra_cluster import _cmd_cluster

        r = _cmd_cluster(["bogus"])
        assert r.get("success") is False

    def test_cmd_cells(self):
        from l2.l2_shell.commands.extra_cluster import _cmd_cells

        r = _cmd_cells([])
        assert r.get("success") is True
        assert r.get("cell")

    def test_cmd_cross(self):
        from l2.l2_shell.commands.extra_cluster import _cmd_cross

        r = _cmd_cross([])
        assert r.get("success") is True
        assert "cross" in r

    def test_cmd_htn_no_args(self):
        from l2.l2_shell.commands.extra_cluster import _cmd_htn

        r = _cmd_htn([])
        assert r.get("success") is False

    def test_cmd_htn_unknown_subcommand(self):
        from l2.l2_shell.commands.extra_cluster import _cmd_htn

        r = _cmd_htn(["bogus"])
        assert r.get("success") is False

    # ── extra_mcp ──

    def test_cmd_mcp_default_status(self):
        from l2.l2_shell.commands.extra_mcp import _cmd_mcp

        # Without a configured MCP bridge this returns a structured error
        # dict (never raises) — the safe-branch contract.
        r = _cmd_mcp([])
        assert isinstance(r, dict)

    # ── extra_security ──

    def test_cmd_security_status(self):
        from l2.l2_shell.commands.extra_security import _cmd_security

        r = _cmd_security([])
        assert r.get("success") is True

    # ── extra_resources ──

    def test_cmd_buffer_no_args(self):
        from l2.l2_shell.commands.extra_resources import _cmd_buffer

        r = _cmd_buffer([])
        assert r.get("success") is True
        assert "buffer" in r

    def test_cmd_think_no_args(self):
        from l2.l2_shell.commands.extra_resources import _cmd_think

        r = _cmd_think([])
        assert r.get("success") is True
        assert "cells" in r

    def test_cmd_think_unknown_subcommand(self):
        from l2.l2_shell.commands.extra_resources import _cmd_think

        r = _cmd_think(["bogus"])
        assert r.get("success") is False

    # ── extra_stats ──

    def test_cmd_stats_no_args(self):
        from l2.l2_shell.commands.extra_stats import _cmd_stats

        r = _cmd_stats([])
        assert r.get("success") is True
        assert "metrics" in r

    def test_cmd_stats_unknown_subcommand(self):
        from l2.l2_shell.commands.extra_stats import _cmd_stats

        r = _cmd_stats(["bogus"])
        assert r.get("success") is False
