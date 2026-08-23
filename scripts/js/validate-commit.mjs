#!/usr/bin/env node
// Validate commit subjects and staged type-content rules from the generated policy mirror.
"use strict";

import fs from "fs";
import { execFileSync } from "child_process";

const msgFile = process.argv[2];
if (!msgFile) {
  console.error("usage: validate-commit.mjs <msg-file>");
  process.exit(2);
}
const msg = fs.readFileSync(msgFile, "utf8");
const first = msg.split("\n")[0].trim();
const match = first.match(/^([a-z]+)(?:\(([^)]+)\))?:/);
if (!match) {
  console.error("subject must be Conventional Commits: type(scope): summary");
  process.exit(1);
}
const type = match[1];
const scope = match[2] || "";
let policy;
try {
  policy = JSON.parse(fs.readFileSync("config/discovery/commits.json", "utf8"));
} catch (error) {
  console.error(`cannot read config/discovery/commits.json: ${error.message}`);
  process.exit(1);
}
if (!(policy.types || []).includes(type)) {
  console.error(`unknown type "${type}"`);
  process.exit(1);
}
if (scope && !(policy.scopes || []).includes(scope)) {
  console.error(`unknown scope "${scope}"`);
  process.exit(1);
}
const summary = first.slice(match[0].length).trim();
if (summary.length > (policy.max_subject_chars || 72) || summary.endsWith(".")) {
  console.error("subject length or punctuation violates the commit policy");
  process.exit(1);
}
const rule = (policy.type_content_rules || {})[type];
const prefixes = Array.isArray(rule) ? rule : (rule && rule.must_include) || [];
if (!prefixes.length) process.exit(0);
const staged = execFileSync("git", ["diff", "--cached", "--name-only", "--diff-filter=ACMR"], { encoding: "utf8" })
  .split("\n")
  .filter(Boolean);
if (staged.length && !staged.some((file) => prefixes.some((prefix) => file.startsWith(prefix)))) {
  console.error(`${type} commit must include one of: ${prefixes.join(", ")}`);
  process.exit(1);
}
