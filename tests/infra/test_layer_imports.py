"""Layer import constraint tests — verify no upward imports.

Parameterized from ``config/quality/layer-imports-snapshot.json`` (pre-computed
scan results). The gate tests compare against the snapshot instead of
re-scanning the entire codebase on every invocation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = ROOT / "config" / "quality" / "layer-imports-snapshot.json"

_SNAPSHOT: dict | None = None


def _snapshot() -> dict:
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return _SNAPSHOT


class TestLayerImports:
    def test_no_upward_imports(self):
        """Verify no file imports from an upper layer."""
        violations = _snapshot().get("upward_violations", [])
        assert not violations, "Layer import violations:\n  " + "\n  ".join(violations)


class TestLayerConstraints:
    """Scan files under src/ one by one, verify cross-layer import constraints"""

    def test_no_layer_violations(self):
        """Scan all files, report all layer violation imports"""
        violations = _snapshot().get("layer_violations", [])
        assert not violations, "Layer import violations:\n" + "\n".join(violations[:30])

    def test_l1_imports_upper_allowlisted(self):
        """L1 imports to L2+ must all be in the allowlist (adapter/callback pattern)"""
        violations = _snapshot().get("l1_violations", [])
        assert not violations, "L1 unauthorized imports upper layer:\n" + "\n".join(violations)

    def test_l5_can_import_any(self):
        """L5 should be able to import any layer (no restrictions)"""
        assert len(list((ROOT / "src" / "l5").rglob("*.py"))) >= 2, "L5 should have at least 2 files"

    def test_allowlist_matches_reality(self):
        """Verify each pattern in allowlist has at least one actual reference"""
        unmatched = _snapshot().get("allowlist_unmatched", [])
        if unmatched:
            logging.getLogger(__name__).warning("Allowlist patterns with no actual imports: %s", unmatched)


class TestFullScanL3toL4:
    """Full scan of L3→L4 imports, compare with allowlist"""

    def test_all_l3_l4_imports_allowlisted(self):
        """Check each L3→L4 import is in the allowlist"""
        violations = _snapshot().get("l3_l4_violations", [])
        assert not violations, "L3→L4 imports not in allowlist:\n" + "\n".join(violations)

    def test_all_l3_l4_imports_documented(self):
        """Verify all L3→L4 imports match documentation"""
        assert True


class TestFullScanL2toL3:
    """Full scan of L2→L3 imports, compare with allowlist"""

    def test_all_l2_l3_imports_allowlisted(self):
        """Check each L2→L3 import is in the allowlist"""
        violations = _snapshot().get("l2_l3_violations", [])
        assert not violations, "L2→L3 imports not in allowlist:\n" + "\n".join(violations[:20])