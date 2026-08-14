"""Commit-scan policy engine — single source of truth for commit gates.

Loads the commit contract from ``config/discovery/commits.yaml`` and
validates Conventional-Commits subjects against it: type whitelist,
registered scopes, placeholder guard (empty / CJK / too-short summaries),
and branch-type policy (``fix*`` branches are fix-only).

Consumed by the gates so the type/scope whitelist lives in ONE place:
- ``.githooks/commit-msg``            (local commit gate)
- ``scripts/sh/verify-pr-merge.sh``   (remote PR merge gate)
- ``scripts/py/generate_changelog.py`` (CHANGELOG typing)
- ``.github/workflows/pr-review.yml`` (PR advisory comment)

Usage (CLI):
    python scripts/py/commit_scan.py --subject "feat(kernel): add x"
    python scripts/py/commit_scan.py --subject "fix: y" --branch fix/foo
Exit: 0 = OK; 1 = violation(s) found (details on stderr).
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_POLICY_PATH = ROOT / "config" / "discovery" / "commits.yaml"

_SUBJECT_RE = re.compile(r"^([a-z]+)(?:\(([^)]+)\))?!?:[ \t]*(.*)$", re.DOTALL)
_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")


def load_policy() -> dict:
    """Load the commit policy from config/discovery/commits.yaml."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML is required to read config/discovery/commits.yaml") from None
    with open(_POLICY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_subject(subject: str) -> tuple[str, str, str] | None:
    """Split a Conventional-Commits subject into (type, scope, summary).

    Returns None when the subject is not conventional (merge/revert
    subjects and anything not matching ``type(scope): summary``).
    """
    m = _SUBJECT_RE.match(subject.strip())
    if not m:
        return None
    return m.group(1), m.group(2) or "", m.group(3).strip()


def validate_subject(subject: str, branch: str = "", policy: dict | None = None) -> list[str]:
    """Validate one subject against the policy; return a list of violations.

    Empty list = the subject is OK. The policy dict is loaded on first
    call and cached; pass an explicit policy to test with a custom one.
    """
    policy = policy if policy is not None else _cached_policy()
    violations: list[str] = []

    parsed = parse_subject(subject)
    if parsed is None:
        return ["subject is not Conventional Commits: `type(scope): summary`"]
    ctype, cscope, summary = parsed

    types = policy.get("types", [])
    if ctype not in types:
        violations.append(f"type '{ctype}' not in whitelist {types}")

    strictness = policy.get("strictness", "strict")
    scopes = policy.get("scopes", [])
    if cscope and cscope not in scopes:
        msg = f"scope '{cscope}' not registered in commits.yaml scopes"
        if strictness == "strict":
            violations.append(msg)
        # relaxed: advisory only — no violation

    placeholder = policy.get("placeholder", {})
    if placeholder.get("reject_empty_summary", True) and not summary:
        violations.append("empty summary — placeholder subject")
    if placeholder.get("reject_cjk_summary", True) and _CJK_RE.search(summary):
        violations.append(f"CJK summary '{summary}' — placeholder subject")
    min_chars = placeholder.get("min_summary_chars", 10)
    if summary and min_chars and len(summary) < min_chars:
        violations.append(f"summary too short ({len(summary)} < {min_chars} chars)")

    # branch-type policy: commits on a pattern-matched branch may only use
    # the branch's allowed types (fix* branches are fix-only).
    for rule in policy.get("branch_policy", {}).get("patterns", []):
        if branch and fnmatch.fnmatch(branch, rule["pattern"]):
            allowed = rule.get("allowed_types", [])
            if ctype not in allowed:
                violations.append(f"branch '{branch}' allows only types {allowed}, got '{ctype}'")

    return violations


_cached = None


def _cached_policy() -> dict:
    global _cached
    if _cached is None:
        _cached = load_policy()
    return _cached


def scan_range(rev_range: str, branch: str = "", policy: dict | None = None) -> list[tuple[str, str]]:
    """Validate every non-merge subject in a git range.

    Returns a list of (commit_short_sha, violation) for every violating
    commit; empty list = the whole range is clean. Merge/Revert subjects
    are skipped (git-generated, exempt per project conventions).
    """
    policy = policy if policy is not None else _cached_policy()
    out = subprocess.run(
        ["git", "log", rev_range, "--pretty=%h|%s", "--no-merges"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    findings: list[tuple[str, str]] = []
    for line in out.stdout.splitlines():
        sha, _, subject = line.partition("|")
        if subject.startswith(("Merge ", "Revert ")):
            continue
        for v in validate_subject(subject, branch=branch, policy=policy):
            findings.append((sha, v))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate commit subject(s) against the project commit policy")
    parser.add_argument("--subject", help="single commit subject line to validate")
    parser.add_argument("--git-range", help="git range (base..head) to scan, e.g. origin/main..HEAD")
    parser.add_argument("--branch", default="", help="branch the commit(s) land on (branch-type policy)")
    args = parser.parse_args()

    try:
        if args.git_range:
            findings = scan_range(args.git_range, branch=args.branch)
            if not findings:
                print("[commit-scan] OK — all subjects in range clean")
                return 0
            print(f"[commit-scan] VIOLATIONS ({len(findings)}):", file=sys.stderr)
            for sha, v in findings:
                print(f"  {sha} ✗ {v}", file=sys.stderr)
            return 1
        if not args.subject:
            parser.error("provide --subject or --git-range")
        violations = validate_subject(args.subject, branch=args.branch)
    except RuntimeError as e:
        print(f"[commit-scan] ERROR: {e}", file=sys.stderr)
        return 2
    if not violations:
        print("[commit-scan] OK")
        return 0
    print("[commit-scan] VIOLATIONS:", file=sys.stderr)
    for v in violations:
        print(f"  ✗ {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
