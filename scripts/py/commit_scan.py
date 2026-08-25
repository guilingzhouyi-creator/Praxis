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

# Type-content consistency rules: a commit type must match the actual diff.
# These are heuristic checks (not absolute) — a `feat` that only touches docs
# is suspicious; a `docs` that touches src/ may be legitimate (docstrings).
_TYPE_CONTENT_RULES: dict[str, dict[str, list[str]]] = {
    "feat": {"must_include": ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"]},
    "fix": {"must_include": ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"]},
    "refactor": {"must_include": ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"]},
    "perf": {"must_include": ["src/", "crates/", "packages/"]},
    "test": {"must_include": ["tests/", "crates/", "packages/"]},
    "ci": {"must_include": [".github/"]},
}

# Imperative-mood fallback — used ONLY when commits.yaml lacks the
# `non_imperative_verbs` key. The registry (config/discovery/commits.yaml)
# is the single source of truth; keep this list in sync with it.
_FALLBACK_NON_IMPERATIVE_VERBS: frozenset[str] = frozenset(
    {
        "added",
        "adding",
        "fixes",
        "fixed",
        "fixing",
        "updated",
        "updating",
        "updates",
        "changes",
        "changed",
        "changing",
        "modified",
        "modifying",
        "modifies",
        "refactored",
        "refactoring",
        "refactors",
        "improves",
        "improved",
        "improving",
        "removes",
        "removed",
        "removing",
        "deletes",
        "deleted",
        "deleting",
        "makes",
        "made",
        "making",
        "creates",
        "created",
        "creating",
        "implements",
        "implemented",
        "implementing",
        "hardens",
        "hardened",
        "hardening",
        "enforces",
        "enforced",
        "enforcing",
        "handles",
        "handled",
        "handling",
        "resolves",
        "resolved",
        "resolving",
        "prevents",
        "prevented",
        "preventing",
        "allows",
        "allowed",
        "allowing",
        "avoids",
        "avoided",
        "avoiding",
        "cleans",
        "cleaned",
        "cleaning",
    }
)


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

    # Imperative verb check: summary should start with an imperative verb,
    # not past tense or gerund. The verb list lives in commits.yaml
    # `non_imperative_verbs` (single source, mirrored to the Node validator);
    # the inline fallback only covers a missing key.
    if summary:
        verbs = policy.get("non_imperative_verbs") or _FALLBACK_NON_IMPERATIVE_VERBS
        first_word = summary.split()[0].lower().rstrip(":,.-")
        if first_word in verbs:
            violations.append(
                f"non-imperative verb '{first_word}' in summary — use imperative present tense "
                "(e.g. 'add', 'fix', 'update', 'refactor', 'remove', 'harden', 'enforce')"
            )

    # subject length guard: Conventional-Commits subjects must stay <= 72
    # chars (AGENTS.md contract). Rejected in strict mode.
    max_chars = policy.get("max_subject_chars", 72)
    if max_chars and len(subject) > max_chars and strictness == "strict":
        violations.append(f"subject too long ({len(subject)} > {max_chars} chars)")

    # branch-type policy: commits on a pattern-matched branch may only use
    # the branch's allowed types (fix* branches are fix-only).
    for rule in policy.get("branch_policy", {}).get("patterns", []):
        if branch and fnmatch.fnmatch(branch, rule["pattern"]):
            allowed = rule.get("allowed_types", [])
            if ctype not in allowed:
                violations.append(f"branch '{branch}' allows only types {allowed}, got '{ctype}'")

    return violations


def validate_type_content(commit_type: str, changed_files: list[str]) -> list[str]:
    """Validate that the commit type is consistent with the changed files.

    A `feat` that does not touch `src/` is suspicious (new features should
    add code). A `fix` that does not touch `src/` is suspicious (bug fixes
    touch code). These are heuristic checks, not absolute — they surface
    inconsistencies that the agent should explain, not block the gate.
    """
    rule = load_policy().get("type_content_rules", _TYPE_CONTENT_RULES).get(commit_type)
    if not rule:
        return []
    prefixes = rule if isinstance(rule, list) else rule.get("must_include", [])
    if not prefixes:
        return []
    # At least one of the allowed prefixes must match a changed file.
    if not any(any(f.startswith(p) for f in changed_files) for p in prefixes):
        return [
            f"type '{commit_type}' does not match any changed file — expected one of: {prefixes}",
        ]
    return []


def validate_scope_content(commit_scope: str, changed_files: list[str], policy: dict | None = None) -> list[str]:
    """Validate that the commit scope is consistent with the changed files.

    A `feat(kernel)` that does not touch `src/l1/kernel/` is suspicious.
    The scope-to-directory mapping lives in commits.yaml `scope_dirs`.
    This is a heuristic advisory, not a hard gate — cross-cutting changes
    may legitimately span directories.
    """
    if not commit_scope or not changed_files:
        return []
    policy = policy if policy is not None else _cached_policy()
    scope_dirs = policy.get("scope_dirs", {})
    expected_dir = scope_dirs.get(commit_scope)
    if not expected_dir:
        return []  # unknown scope — no mapping to check
    if not any(f.startswith(expected_dir) for f in changed_files):
        return [
            f"scope '{commit_scope}' expects files under {expected_dir} but none found",
        ]
    return []


def validate_coauthored_by(msg: str, policy: dict | None = None, detected: dict | None = None) -> list[str]:
    """Validate the Co-Authored-By trailer against the agents registry and
    the live runtime detection.

    The trailer must:
      1. exist exactly once, on its own line, at the end of the message;
      2. match `Co-Authored-By: <Agent> (<model>) <noreply@domain>`;
      3. use a registered agent name (commits.yaml `agents`);
      4. use a model the registered agent is allowed to run;
      5. match the live runtime detection (detect_agent.py) when it reports
         high confidence — an OpenAI/Anthropic run can never claim a deepseek
         model, and a deepseek run can never claim gpt-4o. The detector reads
         env + process-chain signals, not the agent's self-report.

    Returns a list of violations (empty = OK). Never called for merge/revert
    messages (git-generated, exempt).
    """
    policy = policy if policy is not None else _cached_policy()
    violations: list[str] = []

    trailers = re.findall(r"^Co-Authored-By:.*$", msg, flags=re.M)
    if not trailers:
        return ["missing Co-Authored-By trailer"]
    if len(trailers) > 1:
        return [f"exactly ONE Co-Authored-By trailer allowed (found {len(trailers)})"]

    # Strict EOF sentinel: Co-Authored-By must be the VERY LAST non-empty line
    lines = [ln.rstrip() for ln in msg.strip().splitlines()]
    if not lines or not lines[-1].startswith("Co-Authored-By:"):
        violations.append(
            "Co-Authored-By trailer must be the VERY LAST line of the commit message "
            "(no trailing text, notes, or commentary allowed after the trailer)"
        )
    if len(lines) > 1 and lines[-2] != "":
        violations.append("Co-Authored-By trailer must be preceded by a blank line")

    trailer = trailers[0].strip()

    m = re.match(r"^Co-Authored-By: ([^:<>]+) \(([^()]+)\) <noreply@[a-z0-9.-]+>$", trailer)
    if not m:
        return ["Co-Authored-By must match: `Co-Authored-By: <Agent> (<model>) <noreply@domain>`"]
    agent_name, model = m.group(1).strip(), m.group(2).strip()

    agents = {a["name"].lower(): a for a in policy.get("agents", [])}
    reg = agents.get(agent_name.lower())
    if not reg:
        known = ", ".join(sorted(agents)) or "<none registered>"
        return [
            f"agent '{agent_name}' not registered — known agents: {known}. "
            "DO NOT GUESS OR IMPERSONATE: If you are running an unregistered agent, "
            "STOP and notify the human user to register your identity in config/discovery/commits.yaml."
        ]
    if model not in reg.get("models", []):
        return [
            f"model '{model}' not allowed for agent '{reg['name']}' (allowed: {', '.join(reg.get('models', []))}). "
            "DO NOT GUESS OR IMPERSONATE: If this is a new model, "
            "STOP and notify the human user to register it in config/discovery/commits.yaml."
        ]

    # Live-runtime cross-check against EXECUTION EVIDENCE.
    #   - evidence A (session log, confidence high): the model is PROVEN — a
    #     mismatch is a hard violation (impersonation cannot slip through).
    #   - evidence C/D (config/weak, confidence low/none): the model is NOT
    #     execution-verified — claiming a specific model is an unverifiable
    #     assertion, so it is rejected too. Only evidence B (operator pin)
    #     with an explicit model is trusted as a deliberate override.
    if detected:
        det_conf = detected.get("confidence")
        det_model = (detected.get("model") or "").strip().lower()
        det_agent = (detected.get("agent") or "").strip().lower()
        if det_conf == "high" and det_model:
            if det_model != model.lower():
                violations.append(
                    f"model mismatch: trailer says '{model}' but the session log proves '{detected.get('model')}' "
                    f"(provider={detected.get('provider') or '?'}, evidence={detected.get('evidence')}) — "
                    "DO NOT GUESS OR IMPERSONATE: Attribute the ACTUAL running model.",
                )
        elif det_conf == "low" or det_conf == "none":
            # No execution evidence — a specific model claim cannot be proven.
            violations.append(
                f"unverifiable model claim: '{model}' cannot be confirmed by execution evidence "
                f"(confidence={det_conf}, evidence={detected.get('evidence') or 'none'}, framework={detected.get('framework') or 'unknown'}) — "
                "DO NOT GUESS OR IMPERSONATE: Do NOT grab an arbitrary registered agent/model from commits.yaml. "
                "If you are running in a new framework or model, STOP and prompt the user to register your identity in "
                "config/discovery/commits.yaml or set PRAXIS_AUTHOR / PRAXIS_MODEL operator pins.",
            )
        if det_agent and agent_name.lower() not in (det_agent, "atomcode", "opencode", "gemini", "antigravity"):
            # AtomCode/OpenCode/Antigravity/Gemini aliases check
            violations.append(
                f"agent mismatch: trailer says '{agent_name}' but the live session reports '{detected.get('agent')}' "
                f"(framework={detected.get('framework')}) — attribute your ACTUAL running identity.",
            )
    return violations


def body_advisories(body: str, policy: dict | None = None) -> list[str]:
    """Return advisory findings for a commit body (never blocks).

    A non-empty body SHOULD follow the AGENTS.md template (## sections,
    **keywords**, `files`, bullets). Findings guide agents toward uniform,
    changelog-friendly bodies but never fail the gate.
    """
    policy = policy if policy is not None else _cached_policy()
    body = body or ""
    if not body.strip():
        return []  # single-line commits are fine — no body to structure
    rules = policy.get("body", {})
    advisories: list[str] = []
    if rules.get("require_sections") and not re.search(r"^## ", body, re.MULTILINE):
        advisories.append("body lacks '## ' section headings (AGENTS.md template)")
    if rules.get("require_bullets") and not re.search(r"^- ", body, re.MULTILINE):
        advisories.append("body lacks '- ' bullets (AGENTS.md template)")
    if rules.get("require_keywords") and "**" not in body:
        advisories.append("body lacks '**keyword**' emphasis (AGENTS.md template)")
    return advisories


_cached = None


def _cached_policy() -> dict:
    global _cached
    if _cached is None:
        _cached = load_policy()
    return _cached


def scan_range(
    rev_range: str, branch: str = "", policy: dict | None = None, check_content: bool = False
) -> list[tuple[str, str]]:
    """Validate every non-merge subject in a git range.

    When check_content=True, also validates that each commit's type matches
    its changed files (e.g. feat must touch src/, test must touch tests/).

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
        if check_content:
            parsed = parse_subject(subject)
            if parsed:
                ctype = parsed[0]
                files_out = subprocess.run(
                    ["git", "diff", "--name-only", f"{sha}^", f"{sha}"],
                    capture_output=True,
                    text=True,
                    cwd=ROOT,
                )
                changed = [f for f in files_out.stdout.splitlines() if f]
                for v in validate_type_content(ctype, changed):
                    findings.append((sha, v))
                # scope-content is advisory (non-blocking) — scopes are
                # inherently cross-cutting and may span multiple directories.
    return findings


def scan_range_stats(rev_range: str) -> tuple[int, int]:
    """Return (total_commits, merge_or_revert_commits) for a git range.

    The audit counts merge/revert subjects as exempt (git-generated per
    project conventions) — this lets callers report an honest breakdown
    (e.g. "35 validated, 3 merge skipped") instead of a bare total.
    """
    total = subprocess.run(
        ["git", "rev-list", "--count", rev_range],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    merges = subprocess.run(
        ["git", "rev-list", "--count", "--merges", rev_range],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    total_n = int(total.stdout.strip() or 0)
    merges_n = int(merges.stdout.strip() or 0)
    return total_n, merges_n


def scan_range_bodies(rev_range: str, branch: str = "", policy: dict | None = None) -> list[tuple[str, str]]:
    """Validate subjects AND collect body advisories across a git range.

    Returns (sha, advisory) pairs for body-structure findings (never
    blocking). Subjects are validated via validate_subject; the body check
    uses body_advisories so non-uniform bodies are surfaced without failing
    the gate.
    """
    policy = policy if policy is not None else _cached_policy()
    out = subprocess.run(
        ["git", "log", rev_range, "--pretty=%h|%s|%B", "--no-merges"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    advisories: list[tuple[str, str]] = []
    for block in out.stdout.split("\n\n"):
        lines = block.splitlines()
        if not lines:
            continue
        head = lines[0]
        sha, _, subject = head.partition("|")
        if subject.startswith(("Merge ", "Revert ")):
            continue
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        for a in body_advisories(body, policy=policy):
            advisories.append((sha, a))
    return advisories


def _staged_files() -> list[str]:
    """Return staged file names (hook context); [] outside a repo or on error."""
    import subprocess as _sp

    try:
        out = _sp.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
        )
        return [line for line in out.stdout.splitlines() if line]
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate commit subject(s) against the project commit policy")
    parser.add_argument("--subject", help="single commit subject line to validate")
    parser.add_argument("--git-range", help="git range (base..head) to scan, e.g. origin/main..HEAD")
    parser.add_argument("--branch", default="", help="branch the commit(s) land on (branch-type policy)")
    parser.add_argument(
        "--msg",
        help="full commit message: validate Co-Authored-By against the agents registry + live runtime detection",
    )
    parser.add_argument("--detected", help="optional JSON from scripts/py/detect_agent.py (defaults to live detection)")
    parser.add_argument(
        "--check-content",
        action="store_true",
        help="validate type-diff consistency (feat must touch src/, test must touch tests/, etc.)",
    )
    args = parser.parse_args()

    try:
        if args.git_range:
            findings = scan_range(args.git_range, branch=args.branch, check_content=args.check_content)
            # Report the honest breakdown: merge/revert commits are exempt
            # (git-generated) and skipped by scan_range — a bare total (e.g.
            # push-both's "38 commit(s) checked") would silently overstate.
            total, merges = scan_range_stats(args.git_range)
            if not findings:
                print(
                    f"[commit-scan] OK — all subjects in range clean "
                    f"({total - merges} validated, {merges} merge/revert skipped)"
                )
            else:
                print(f"[commit-scan] VIOLATIONS ({len(findings)}):", file=sys.stderr)
                for sha, v in findings:
                    print(f"  {sha} ✗ {v}", file=sys.stderr)
            # Body-structure advisories (never blocking) — surface non-uniform
            # bodies so agents align them without failing the gate.
            advisories = scan_range_bodies(args.git_range, branch=args.branch)
            if advisories:
                print(f"[commit-scan] BODY ADVISORIES ({len(advisories)}):")
                for sha, a in advisories:
                    print(f"  {sha} ⚠ {a}")
            return 1 if findings else 0
        if args.msg:
            # Co-Authored-By truthfulness gate: compare the trailer the agent
            # wrote against the agents registry + live runtime detection.
            import json as _json

            detected = None
            if args.detected:
                try:
                    detected = _json.loads(args.detected)
                except _json.JSONDecodeError:
                    detected = None
            if detected is None:
                try:
                    out = subprocess.run(
                        [sys.executable, str(ROOT / "scripts" / "py" / "detect_agent.py"), "--json"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    detected = _json.loads(out.stdout) if out.stdout.strip() else None
                except Exception:
                    detected = None
            violations = validate_coauthored_by(args.msg, detected=detected)
            # Full contract for complete-message validation (commit-msg hook
            # fallback when node is absent — mirrors validate-commit.mjs):
            # subject shape + branch-type policy + staged type/scope content.
            subject = args.msg.splitlines()[0] if args.msg else ""
            violations += validate_subject(subject, branch=args.branch)
            parsed = parse_subject(subject)
            staged = _staged_files() if args.check_content else []
            if parsed and staged:
                # Content checks only fire when --check-content is requested and staged files exist
                ctype, cscope, _summary = parsed
                violations += validate_type_content(ctype, staged)
                violations += validate_scope_content(cscope, staged)
            if not violations:
                print(
                    "[commit-scan] OK — Co-Authored-By matches registry + runtime"
                    + (f" (detected: {detected.get('agent')}/{detected.get('model')})" if detected else "")
                )
            else:
                print("[commit-scan] VIOLATIONS:", file=sys.stderr)
                for v in violations:
                    print(f"  ✗ {v}", file=sys.stderr)
            return 1 if violations else 0
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
