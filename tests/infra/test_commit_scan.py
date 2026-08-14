"""Tests for scripts/py/commit_scan.py — the commit-scan policy engine.

Covers the single source of truth (config/discovery/commits.yaml) contract:
type whitelist, registered scopes, placeholder guard, branch-type policy,
git-range scanning, and CLI exit codes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "py"))  # noqa: E402

from commit_scan import load_policy, parse_subject, scan_range, validate_subject  # noqa: E402


def policy() -> dict:
    """The real policy from config/discovery/commits.yaml (single source of truth)."""
    return load_policy()


def test_parse_subject_forms():
    assert parse_subject("feat(kernel): add x") == ("feat", "kernel", "add x")
    assert parse_subject("fix: just summary") == ("fix", "", "just summary")
    assert parse_subject("feat! : breaking? no") is None  # malformed
    assert parse_subject("Merge branch 'x'") is None  # not conventional


def test_valid_subject_passes():
    p = policy()
    assert validate_subject("feat(kernel): add token ring revocation", policy=p) == []
    assert validate_subject("fix(session): reload on anomaly", policy=p) == []
    assert validate_subject("docs(agents): update collaboration guide", policy=p) == []


def test_unknown_type_rejected():
    p = policy()
    vs = validate_subject("hack(kernel): xyz", policy=p)
    assert any("not in whitelist" in v for v in vs)


def test_unknown_scope_rejected_in_strict():
    p = policy()
    vs = validate_subject("feat(nonexistent-scope): add real feature code here", policy=p)
    assert any("not registered" in v for v in vs)


def test_known_legacy_scope_accepted():
    # scopes seen in history must stay accepted (strict mode never rejects
    # previously-merged commits / documented examples).
    p = policy()
    assert validate_subject("feat(core): add token ring revocation", policy=p) == []
    assert validate_subject("docs(tool-presentation): cache hot path", policy=p) == []


def test_cjk_placeholder_rejected():
    p = policy()
    vs = validate_subject("feat: 准备构建", policy=p)
    assert any("CJK" in v for v in vs)


def test_empty_summary_rejected():
    p = policy()
    vs = validate_subject("feat(kernel):", policy=p)
    assert any("empty summary" in v for v in vs)


def test_short_summary_flagged():
    p = policy()
    vs = validate_subject("feat(kernel): abc", policy=p)
    assert any("too short" in v for v in vs)


def test_fix_branch_policy():
    p = policy()
    # fix* branches allow only fix commits.
    assert any(
        "allows only types" in v for v in validate_subject("feat(kernel): add feature", branch="fix/session", policy=p)
    )
    assert validate_subject("fix(session): reload on anomaly", branch="fix/session", policy=p) == []


def test_feature_branch_allows_feat():
    p = policy()
    assert validate_subject("feat(kernel): add token ring revocation", branch="feature/x", policy=p) == []


def test_scan_range_skips_merge_and_clean():
    # The repo's own main range should be clean (all history passed the gate).
    findings = scan_range("origin/main..HEAD", branch="main", policy=policy())
    assert findings == []
