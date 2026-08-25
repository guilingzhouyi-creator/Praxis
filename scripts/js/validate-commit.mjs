#!/usr/bin/env node
// Commit-msg validator (Node) — type/scope registration, subject format and
// must_include (type-to-file matching). Mirrors scripts/py/commit_scan.py
// rules so the commit-time gate and the push-time audit stay in sync.
//
// Usage: node scripts/js/validate-commit.mjs <msg-file>
// Reads staged files via `git diff --cached` for the must_include check.
"use strict";

import fs from "fs";
import { execFileSync } from "child_process";

const msgFile = process.argv[2];
if (!msgFile) {
  console.error("usage: validate-commit.mjs <msg-file>");
  process.exit(2);
}
const msg = fs.readFileSync(msgFile, "utf8");

// ── 1. Conventional Commits subject: type(scope): summary ──────────────
const first = msg.split("\n")[0].trim();
const m = first.match(/^([a-z]+)(?:\(([^)]+)\))?:/);
if (!m) {
  console.error('❌ subject must be Conventional Commits: type(scope): summary');
  process.exit(1);
}
const type = m[1];
const scope = m[2] || "";

// ── 2. type / scope registration (config/discovery/commits.json) ────────
let policy = { types: [], scopes: [], max_subject_chars: 72 };
try {
  policy = JSON.parse(fs.readFileSync("config/discovery/commits.json", "utf8"));
} catch (e) {
  console.error(`❌ cannot read config/discovery/commits.json: ${e.message}`);
  process.exit(1);
}
const types = policy.types || [];
if (!types.includes(type)) {
  console.error(`❌ unknown type "${type}" — allowed: ${types.join(", ")}`);
  process.exit(1);
}
if (scope && !(policy.scopes || []).includes(scope)) {
  console.error(`❌ unknown scope "${scope}" — see config/discovery/commits.yaml scopes`);
  process.exit(1);
}

// ── 3. subject format: length cap, no trailing period ───────────────────
const maxLen = policy.max_subject_chars || 72;
const summary = first.slice(m[0].length).trim();
if (summary.length > maxLen) {
  console.error(`❌ summary is ${summary.length} chars (max ${maxLen})`);
  process.exit(1);
}
if (summary.endsWith(".")) {
  console.error("❌ summary must not end with a period");
  process.exit(1);
}

const NON_IMPERATIVE = new Set([
  "added", "adding", "fixes", "fixed", "fixing",
  "updated", "updating", "updates",
  "changes", "changed", "changing",
  "modified", "modifying", "modifies",
  "refactored", "refactoring", "refactors",
  "improves", "improved", "improving",
  "removes", "removed", "removing",
  "deletes", "deleted", "deleting",
  "makes", "made", "making",
  "creates", "created", "creating",
  "implements", "implemented", "implementing",
  "hardens", "hardened", "hardening",
  "enforces", "enforced", "enforcing",
  "handles", "handled", "handling",
  "resolves", "resolved", "resolving",
  "prevents", "prevented", "preventing",
  "allows", "allowed", "allowing",
  "avoids", "avoided", "avoiding",
  "cleans", "cleaned", "cleaning",
]);
const firstWord = (summary.split(/\s+/)[0] || "").toLowerCase().replace(/[:,.-]+$/, "");
if (NON_IMPERATIVE.has(firstWord)) {
  console.error(`❌ non-imperative verb "${firstWord}" in summary — use imperative present tense (e.g. "add", "fix", "update", "refactor", "remove", "harden", "enforce")`);
  process.exit(1);
}

// ── 4. must_include — staged files must match the type's content rule ───
// Rules come from commits.yaml via the commits.json mirror (single source of
// truth shared with commit_scan.py); inline defaults are the fallback.
const FALLBACK_TYPE_RULES = {
  feat: ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"],
  fix: ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"],
  refactor: ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"],
  perf: ["src/", "crates/", "packages/"],
  test: ["tests/", "crates/", "packages/"],
  ci: [".github/"],
};
const TYPE_RULES = policy.type_content_rules || FALLBACK_TYPE_RULES;
const rule = TYPE_RULES[type];
const prefixes = Array.isArray(rule) ? rule : (rule && rule.must_include) || [];
if (prefixes.length) {
  let staged = [];
  try {
    staged = execFileSync("git", ["diff", "--cached", "--name-only", "--diff-filter=ACMR"], {
      encoding: "utf8",
    })
      .split("\n")
      .filter(Boolean);
  } catch {
    /* no staged files readable — fall through to the empty check */
  }
  if (!staged.length) {
    // No staged files to match against (e.g. --allow-empty): nothing to
    // verify here — the push-time audit (commit_scan.py --check-content)
    // remains the backstop. Rejecting here would block legitimate commits.
    process.exit(0);
  }
  const hit = staged.some((f) => prefixes.some((p) => f.startsWith(p)));
  if (!hit) {
    console.error(
      `❌ ${type} commit must include: ${prefixes.join(", ")} (staged: ${staged.join(", ") || "none"})`
    );
    process.exit(1);
  }
}

process.exit(0);
