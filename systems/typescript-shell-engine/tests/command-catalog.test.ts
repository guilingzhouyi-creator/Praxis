/**
 * CommandCatalog tests — YAML-subset parsing, alias index, revisions.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CommandCatalog,
  HELP_DISPLAY_LIMIT,
  parseCommandCatalog,
} from "../src/engine/command-catalog.ts";

const SAMPLE_YAML = `
# commands.yaml — L2 Shell command definitions
help:
  category: session
  help: "Show available commands"
  examples:
    - "/help              — list all commands"
    - "/help memory       — show memory command details"

agents:
  category: session
  help: "List all agents"
  aliases: ["ls"]
  examples:
    - "/agents            — list all agents across cells"

connect:
  category: session
  help: "Connect to an agent (direct mode)"
  args:
    - {name: agent_id, completer: agent, description: "Target agent ID"}
    - {name: "--role", completer: role, optional: true, description: "Filter by role"}
  examples:
    - "/connect agent-writer          — connect to an agent"

mode:
  category: session
  help: "Show/switch mode (L3A/Direct, tool read/write)"
  args:
    - {name: sub, optional: true, description: "'tool' for tool mode"}
`;

describe("command catalog parsing", () => {
  it("loads top-level commands with scalar fields", () => {
    const catalog = parseCommandCatalog(SAMPLE_YAML);
    expect(catalog.commandNames()).toEqual(["agents", "connect", "help", "mode"]);
    expect(catalog.get("help")).toMatchObject({
      name: "help",
      category: "session",
      help: "Show available commands",
    });
  });

  it("parses flow-list aliases and builds the reverse index", () => {
    const catalog = parseCommandCatalog(SAMPLE_YAML);
    expect(catalog.get("agents")?.aliases).toEqual(["ls"]);
    expect(catalog.resolveAlias("ls")).toBe("agents");
    expect(catalog.resolveAlias("nope")).toBeUndefined();
    expect(catalog.aliases()).toEqual(["ls"]);
  });

  it("parses flow-object args with optional and completer", () => {
    const catalog = parseCommandCatalog(SAMPLE_YAML);
    const args = catalog.get("connect")?.args ?? [];
    expect(args).toHaveLength(2);
    expect(args[0]).toEqual({
      name: "agent_id",
      completer: "agent",
      optional: false,
      description: "Target agent ID",
    });
    expect(args[1]).toMatchObject({ name: "--role", optional: true });
  });

  it("parses block-list examples as strings", () => {
    const catalog = parseCommandCatalog(SAMPLE_YAML);
    expect(catalog.get("connect")?.examples[0]).toContain("/connect agent-writer");
  });

  it("keeps quotes inside scalar values and strips comments", () => {
    const catalog = parseCommandCatalog(SAMPLE_YAML);
    expect(catalog.get("mode")?.args[0]?.description).toBe("'tool' for tool mode");
    expect(catalog.get("help")?.examples).toHaveLength(2);
  });

  it("degrades gracefully on malformed input", () => {
    const catalog = parseCommandCatalog("not: [valid\n  dangling");
    // The top-level key still registers defensively; the dangling field
    // and unparseable rest are ignored — no crash, no noise entries.
    expect(catalog.commandNames()).toEqual(["not"]);
    expect(catalog.get("not")).toMatchObject({ name: "not", aliases: [], args: [], examples: [] });
    expect(parseCommandCatalog("  only-nested").commandNames()).toEqual([]);
    expect(parseCommandCatalog("# just a comment\n").commandNames()).toEqual([]);
  });

  it("sorts names and exposes revisions", () => {
    const catalog = new CommandCatalog();
    expect(catalog.revision()).toBe(0);
    catalog.loadDefaults("a:\n  category: session\nb:\n  category: session");
    expect(catalog.revision()).toBe(1);
    expect(catalog.commandNames()).toEqual(["a", "b"]);
    catalog.loadDefaults("x:\n  category: session");
    expect(catalog.revision()).toBe(2);
    expect(catalog.commandNames()).toEqual(["x"]);
  });

  it("invalidates the name cache even when the entry count is unchanged", () => {
    const catalog = parseCommandCatalog("a:\n  category: session\nb:\n  category: session");
    expect(catalog.commandNames()).toEqual(["a", "b"]);
    // Same count, different names: the old cache must not be served.
    catalog.loadDefaults("y:\n  category: session\nz:\n  category: session");
    expect(catalog.commandNames()).toEqual(["y", "z"]);
    expect(catalog.has("a")).toBe(false);
    expect(catalog.get("y")?.category).toBe("session");
  });

  it("keeps helper display limit constant in sync with the reference", () => {
    // SHELL_AUTOCOMPLETE_DISPLAY_LIMIT in kernel params/system.py
    expect(HELP_DISPLAY_LIMIT).toBe(15);
  });
});

// Full-file smoke test against the REAL shared metadata (single source of
// truth: config/commands.yaml). Skips when the repo layout is unavailable.
const COMMANDS_YAML = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../../config/commands.yaml",
);

describe("command catalog against the real commands.yaml", () => {
  const catalog = existsSync(COMMANDS_YAML) ? parseCommandCatalog(readFileSync(COMMANDS_YAML, "utf8")) : null;

  it("parses the full command surface without loss", () => {
    if (!catalog) return; // repo layout unavailable — nothing to verify
    expect(catalog.commandNames().length).toBeGreaterThan(30);
    for (const name of catalog.commandNames()) {
      const entry = catalog.get(name)!;
      expect(entry.help.length).toBeGreaterThan(0);
    }
  });

  it("resolves documented aliases from the real file", () => {
    if (!catalog) return;
    expect(catalog.resolveAlias("ls")).toBe("agents");
    expect(catalog.resolveAlias("dc")).toBe("disconnect");
    expect(catalog.resolveAlias("mem")).toBe("memory");
  });

  it("parses args entries with completers and optional flags", () => {
    if (!catalog) return;
    const connect = catalog.get("connect");
    expect(connect?.args[0]).toMatchObject({ name: "agent_id", completer: "agent", optional: false });
  });
});