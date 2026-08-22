#!/usr/bin/env node
/**
 * Validate a commit message against Praxis governance rules.
 *
 * Reads the commit message from the file path passed as the first argument
 * and validates it against config/discovery/commits.json. Exits 0 on
 * success, 1 on failure (error message on stderr).
 *
 * This replaces the Python3-based commit_scan.py + detect_agent.py calls
 * from the .githooks/commit-msg hook, removing the Python3 runtime dependency.
 */

import { readFileSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { spawnSync } from "child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..", "..");
const CONFIG_PATH = resolve(ROOT, "config", "discovery", "commits.json");

// ── Helpers ──────────────────────────────────────────────────────────

function loadConfig() {
  if (!existsSync(CONFIG_PATH)) {
    console.error("❌ commits.json not found — cannot validate commit message", CONFIG_PATH);
    process.exit(1);
  }
  return JSON.parse(readFileSync(CONFIG_PATH, "utf-8"));
}

function hasCJK(text) {
  // eslint-disable-next-line no-control-regex
  return /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]/.test(text);
}

// ── Main ─────────────────────────────────────────────────────────────

const msgFile = process.argv[2];
if (!msgFile) {
  console.error("❌ usage: validate-commit.mjs <commit-message-file>");
  process.exit(1);
}

const msg = readFileSync(msgFile, "utf-8");
const lines = msg.split("\n");
const firstLine = lines[0]?.trim() || "";
const config = loadConfig();

const errors = [];
const types = config.types || [];
const scopes = config.scopes || [];
const agents = config.agents || {};
const coauthPattern = /^Co-Authored-By:\s*(.+?)\s*\((.+?)\)\s*<(.+?)>$/;

// ── 1. Merge / Revert exemption ──
if (/^(Merge|Revert)\s/.test(firstLine)) {
  process.exit(0);
}

// ── 2. English subject (reject CJK) ──
if (hasCJK(firstLine)) {
  errors.push("subject contains CJK (Chinese/Japanese/Korean) characters — must be English");
}

// ── 3. Conventional Commits format ──
const ccMatch = firstLine.match(/^([a-z]+)(?:\(([^)]+)\))?:\s*(.+)$/);
if (!ccMatch) {
  errors.push(`subject does not match Conventional Commits format: "type(scope): summary"`);
} else {
  const [, type, scope, summary] = ccMatch;

  // Type whitelist
  if (!types.includes(type)) {
    errors.push(`unknown type "${type}" — allowed: ${types.join(", ")}`);
  }

  // Scope whitelist (optional)
  if (scope && !scopes.includes(scope)) {
    errors.push(`scope "${scope}" not registered in commits.yaml scopes`);
  }

  // Type-to-file matching (must_include) — mirrors commit_scan.py
  // MUST_INCLUDE so the gate fires at commit time, not at push time.
  const MUST_INCLUDE = {
    feat: ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"],
    fix: ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"],
    refactor: ["src/", "crates/", "packages/", "scripts/", ".githooks/", "config/"],
    perf: ["src/", "crates/", "packages/"],
    test: ["tests/", "crates/", "packages/"],
  };
  const expected = MUST_INCLUDE[type];
  if (expected) {
    const staged = spawnSync(
      "git", ["diff", "--cached", "--name-only", "--diff-filter=ACMR"],
      { encoding: "utf-8" },
    ).stdout?.split("\n").filter(Boolean) || [];
    // Skip when nothing is staged (amend / message-only paths) — the
    // type-to-file rule applies to fresh commits that carry content.
    if (staged.length > 0 && !expected.some((prefix) => staged.some((f) => f.startsWith(prefix)))) {
      errors.push(
        `type "${type}" does not match any changed file — expected one of: [${expected.join(", ")}]`,
      );
    }
  }

  // Summary length
  if (summary.length > 72) {
    errors.push(`summary is ${summary.length} chars (max 72)`);
  }

  // No trailing period
  if (summary.endsWith(".")) {
    errors.push("summary must not end with a period");
  }

  // Subject must start with lowercase
  if (/^[A-Z]/.test(type)) {
    errors.push("type must be lowercase");
  }
}

// ── 4. Co-Authored-By trailer ──
// Find the last non-empty line that matches Co-Authored-By
let coauthLine = null;
for (let i = lines.length - 1; i >= 0; i--) {
  const trimmed = lines[i].trim();
  if (trimmed === "") continue;
  if (coauthPattern.test(trimmed)) {
    coauthLine = trimmed;
    break;
  }
  // Non-empty line that doesn't match Co-Authored-By means no trailer
  break;
}

if (!coauthLine) {
  errors.push("missing Co-Authored-By trailer (last non-empty line)");
}

// ── 5. Model attribution check ──
const modelMatch = msg.match(coauthPattern);
if (modelMatch) {
  const [, agentName, modelName] = modelMatch;
  // Find agent in the registered list (agents is an array of {name, models, email})
  const agentEntry = agents.find((a) => a.name === agentName);
  if (!agentEntry) {
    const known = agents.map((a) => a.name).join(", ");
    errors.push(`agent "${agentName}" not registered in commits.yaml agents — known: ${known}`);
  } else if (agentEntry.models && !agentEntry.models.includes(modelName)) {
    const allowed = agentEntry.models.join(", ");
    errors.push(`model "${modelName}" not allowed for agent "${agentName}" — allowed: ${allowed}`);
  }
}

// ── Report ──
if (errors.length > 0) {
  for (const err of errors) {
    console.error(`❌ ${err}`);
  }
  console.error("\n   Fix the message, or set PRAXIS_SKIP_AUTHOR_CHECK=1 to bypass.");
  process.exit(1);
}

process.exit(0);