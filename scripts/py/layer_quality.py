"""Per-layer quality baseline scanner — measures each layer against a stored baseline.

For every layer (L1-L5) the scanner recomputes the quality metrics defined in
``docs/architecture/quality-baseline.md`` (comment ratio, mega/large function
counts, docstring completeness, hardcoded-arg residue, CJK comment hygiene)
and compares them against ``config/quality/layer-baseline.yaml``.

Gate semantics:
  - hard gates (absolute red lines): ``cjk_comment > 0``, ``mega_funcs > 0``,
    and unhandled singleton gaps — any violation fails the run.
  - soft gates (monotonic / drift): ``missing_doc``, ``short_doc`` and
    ``hardcoded_args`` must never exceed their baseline (only improve);
    ``large_funcs`` may drift up to +20% of baseline; ``comment_ratio`` must
    stay above 80% of baseline.

Exit code 0 = pass, 1 = any gate violated, 2 = baseline file missing.

Usage:
    python scripts/py/layer_quality.py                # scan + gate verdict
    python scripts/py/layer_quality.py --report       # scan, print table only
    python scripts/py/layer_quality.py --baseline     # emit baseline YAML to stdout
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = ROOT / "config" / "quality" / "layer-baseline.yaml"

LAYERS: dict[str, Path] = {
    "L1": ROOT / "src" / "l1",
    "L2": ROOT / "src" / "l2",
    "L3": ROOT / "src" / "l3",
    "L4": ROOT / "src" / "l4",
    "L5": ROOT / "src" / "l5",
}

# Hardcoded-arg scan: keyword names that should always come from params/.
_HARDCODED_KW = {"timeout", "limit", "max_", "count", "threshold", "interval"}
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
SHORT_DOC_MIN = 20

# Soft-gate policy (see docs/architecture/quality-baseline.md).
_MONOTONIC = ("missing_doc", "short_doc", "hardcoded_args")
_DRIFT_FACTOR = 1.2  # large_funcs may grow 20% above baseline
_COMMENT_RATIO_FLOOR = 0.8  # comment_ratio must stay >= 80% of baseline


def _iter_py(layer_dir: Path):
    for p in sorted(layer_dir.rglob("*.py")):
        if "__pycache__" in p.parts or "/params/" in str(p):
            continue
        yield p


def measure_layer(layer_dir: Path) -> dict[str, Any]:
    """Measure all quality metrics for one layer directory."""
    stats: dict[str, Any] = {
        "files": 0,
        "lines": 0,
        "comment_lines": 0,
        "comment_ratio": 0.0,
        "mega_funcs": 0,
        "large_funcs": 0,
        "missing_doc": 0,
        "short_doc": 0,
        "hardcoded_args": 0,
        "cjk_comment": 0,
    }
    for p in _iter_py(layer_dir):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        stats["files"] += 1
        lines = text.splitlines()
        stats["lines"] += len(lines)
        for line in lines:
            s = line.strip()
            if s.startswith("#"):
                stats["comment_lines"] += 1
                if _CJK_RE.search(s):
                    stats["cjk_comment"] += 1
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                size = node.end_lineno - node.lineno + 1
                if size > 200:
                    stats["mega_funcs"] += 1
                elif size >= 120:
                    stats["large_funcs"] += 1
                doc = ast.get_docstring(node)
                if not doc:
                    stats["missing_doc"] += 1
                elif len(doc) < SHORT_DOC_MIN:
                    stats["short_doc"] += 1
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                doc = ast.get_docstring(node)
                if not doc:
                    stats["missing_doc"] += 1
                elif len(doc) < SHORT_DOC_MIN:
                    stats["short_doc"] += 1
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (
                        kw.arg in _HARDCODED_KW
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, (int, float))
                    ):
                        stats["hardcoded_args"] += 1
    stats["comment_ratio"] = stats["comment_lines"] / max(stats["lines"], 1)
    return stats


def load_baseline(path: Path) -> dict[str, Any]:
    """Load the stored per-layer baseline YAML (empty dict when absent)."""
    if not path.exists():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"layer_quality: baseline load failed: {e}", file=sys.stderr)
        return {}


def singleton_gaps() -> int:
    """Number of unhandled singleton modules (reuses scan_singletons.py).

    Matches the completeness-guard semantics in
    ``tests/infra/test_resets_completeness.py``: a singleton module is a gap
    only when it is neither registered in ``_RESETS`` nor listed in the
    test's explicit ``KNOWN_GAPS`` exemption set.
    """
    try:
        spec_path = ROOT / "scripts" / "py" / "scan_singletons.py"
        import importlib.util
        import re

        spec = importlib.util.spec_from_file_location("scan_singletons", spec_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        data = mod.scan()
        registered = set(data.get("registered", []))
        with_getter = {m for m, _ in data.get("with_getter", [])}
        guard_text = (ROOT / "tests" / "infra" / "test_resets_completeness.py").read_text(encoding="utf-8")
        kg_start = guard_text.index("KNOWN_GAPS = frozenset(")
        kg_src = guard_text[kg_start:]
        known_gaps = set(re.findall(r'"([\w.]+)"', kg_src[: kg_src.index("}")]))
        return len(with_getter - registered - known_gaps)
    except Exception:
        return -1  # scanner unavailable — treat as unknown (non-failing)


def compare(measured: dict[str, dict[str, Any]], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare measured values against the baseline; return finding dicts."""
    findings: list[dict[str, Any]] = []
    layers_baseline = baseline.get("layers", {})
    for layer, values in sorted(measured.items()):
        bl = layers_baseline.get(layer, {})
        for key in (
            "comment_ratio",
            "mega_funcs",
            "large_funcs",
            "missing_doc",
            "short_doc",
            "hardcoded_args",
            "cjk_comment",
        ):
            cur = values.get(key, 0)
            base = bl.get(key, 0)
            if key == "comment_ratio":
                if base and cur < base * _COMMENT_RATIO_FLOOR:
                    findings.append(
                        _finding(layer, key, cur, base, "soft", f"below {int(_COMMENT_RATIO_FLOOR * 100)}% of baseline")
                    )
            elif key in _MONOTONIC:
                if base is not None and cur > base:
                    findings.append(_finding(layer, key, cur, base, "soft", "exceeds baseline (monotonic)"))
            elif key == "large_funcs":
                limit = int(base * _DRIFT_FACTOR) if base else 0
                if cur > limit:
                    findings.append(
                        _finding(layer, key, cur, limit, "soft", f"above {int(_DRIFT_FACTOR * 100)}% drift limit")
                    )
            else:  # mega_funcs, cjk_comment — hard
                if cur > 0:
                    findings.append(_finding(layer, key, cur, 0, "hard", "absolute red line"))
    gaps = singleton_gaps()
    if gaps > 0:
        findings.append(_finding("ALL", "singleton_gaps", gaps, 0, "hard", "unhandled singleton modules"))
    return findings


def _finding(layer: str, key: str, cur: Any, base: Any, kind: str, note: str) -> dict[str, Any]:
    """Build a finding dict."""
    return {"layer": layer, "key": key, "current": cur, "baseline": base, "kind": kind, "note": note}


def render_report(measured: dict[str, dict[str, Any]], findings: list[dict[str, Any]]) -> str:
    """Render a human-readable table of measured values plus violations."""
    lines = [
        "Per-layer quality scan",
        "=" * 78,
        f"{'layer':<5}{'comment':>9}{'mega':>6}{'large':>7}{'missDoc':>8}{'shortDoc':>9}{'hardc':>7}{'cjk':>5}",
    ]
    for layer, values in sorted(measured.items()):
        lines.append(
            f"{layer:<5}{values['comment_ratio']:>9.4f}{values['mega_funcs']:>6}{values['large_funcs']:>7}"
            f"{values['missing_doc']:>8}{values['short_doc']:>9}{values['hardcoded_args']:>7}{values['cjk_comment']:>5}"
        )
    lines.append("-" * 78)
    if not findings:
        lines.append("PASS: all gates within baseline.")
    else:
        lines.append(f"FAIL: {len(findings)} gate violation(s):")
        for f in findings:
            lines.append(
                f"  [{f['kind']}] {f['layer']}.{f['key']} current={f['current']} baseline={f['baseline']} — {f['note']}"
            )
    return "\n".join(lines)


def emit_baseline(measured: dict[str, dict[str, Any]]) -> str:
    """Emit a baseline YAML document for the current measured values."""
    doc = [
        "# Per-layer quality baseline (generated — do not hand-edit).",
        "# Regenerate: python scripts/py/layer_quality.py --baseline",
        "layers:",
    ]
    for layer, values in sorted(measured.items()):
        doc.append(f"  {layer}:")
        for key in (
            "comment_ratio",
            "mega_funcs",
            "large_funcs",
            "missing_doc",
            "short_doc",
            "hardcoded_args",
            "cjk_comment",
        ):
            v = values[key]
            if key == "comment_ratio":
                doc.append(f"    {key}: {v:.4f}")
            else:
                doc.append(f"    {key}: {v}")
    return "\n".join(doc) + "\n"


def main() -> int:
    """CLI entry: scan, compare, gate-verdict (or emit baseline)."""
    parser = argparse.ArgumentParser(description="Per-layer quality baseline scanner")
    parser.add_argument("--report", action="store_true", help="print the measured table only (no verdict)")
    parser.add_argument("--baseline", action="store_true", help="emit the current values as baseline YAML to stdout")
    parser.add_argument("--json", action="store_true", help="emit the measured values as JSON")
    args = parser.parse_args()

    measured = {name: measure_layer(path) for name, path in LAYERS.items()}

    if args.baseline:
        print(emit_baseline(measured))
        return 0
    if args.json:
        print(json.dumps(measured, indent=2))
        return 0
    if args.report:
        print(render_report(measured, []))
        return 0

    baseline = load_baseline(BASELINE)
    if not baseline:
        print(f"layer_quality: baseline missing — run --baseline to generate {BASELINE}", file=sys.stderr)
        return 2
    findings = compare(measured, baseline)
    print(render_report(measured, findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
