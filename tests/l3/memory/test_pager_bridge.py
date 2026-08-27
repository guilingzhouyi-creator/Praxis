"""Pager bridge tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "systems/python-reference-runtime"))


class TestPagerBridge:
    def test_importable(self):
        from l3.memory.pager_bridge import PagerBridge

        assert callable(PagerBridge)
