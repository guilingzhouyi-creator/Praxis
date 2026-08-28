/**
 * TerminalView tests — projection shapes mirroring the Python3
 * TerminalShell result dictionaries.
 */

import { describe, expect, it } from "vitest";
import { parseCommandCatalog } from "../src/engine/command-catalog.ts";
import {
  helpView,
  intentView,
  LOG_TRUNC_200,
  scoutView,
  SCOUT_FINDINGS_DISPLAY_LIMIT,
  systemView,
  toolResultView,
  toolsView,
} from "../src/engine/terminal-view.ts";

const CATALOG = parseCommandCatalog(`
help:
  category: session
  help: "Show available commands"
agents:
  category: session
  help: "List all agents"
  aliases: ["ls"]
`);

describe("help/tools views", () => {
  it("builds help entries from catalog metadata with a more-count", () => {
    const view = helpView(CATALOG);
    expect(view.success).toBe(true);
    expect(view.commands).toEqual([
      { name: "agents", help: "List all agents" },
      { name: "help", help: "Show available commands" },
    ]);
    expect(view.more).toBe(0);
  });

  it("counts commands beyond the display limit as more", () => {
    const big = parseCommandCatalog(
      Array.from({ length: 20 }, (_, i) => `cmd${i}:\n  help: "h${i}"`).join("\n"),
    );
    const view = helpView(big);
    expect(view.commands).toHaveLength(15);
    expect(view.more).toBe(5);
  });

  it("builds the tools view with a total", () => {
    const view = toolsView([
      { name: "read_file", description: "Read a file" },
      { name: "grep", description: "Search text" },
    ]);
    expect(view).toEqual({
      success: true,
      type: "tools",
      tools: [
        { name: "read_file", description: "Read a file" },
        { name: "grep", description: "Search text" },
      ],
      total: 2,
    });
  });
});

describe("intent/scout views", () => {
  it("projects a successful intent payload with placeholder defaults", () => {
    const view = intentView({
      success: true,
      intent: "write a card",
      card_id: "c-1",
      domain: "ops",
      agent: "writer",
      card_type: "card",
    });
    expect(view).toMatchObject({
      success: true,
      type: "intent",
      intent: "write a card",
      card_id: "c-1",
      domain: "ops",
      agent: "writer",
      card_type: "card",
    });
  });

  it("projects a failed intent with error and question marks", () => {
    const view = intentView({ success: false, intent: "x", error: "parse failed" });
    expect(view).toMatchObject({ success: false, card_id: "?", error: "parse failed" });
  });

  it("truncates and caps scout findings", () => {
    const long = "f".repeat(LOG_TRUNC_200 + 50);
    const view = scoutView({
      success: true,
      task: "investigate",
      status: "done",
      findings: Array.from({ length: SCOUT_FINDINGS_DISPLAY_LIMIT + 3 }, (_, i) =>
        i === 0 ? long : `finding-${i}`,
      ),
    });
    expect(view.findings).toHaveLength(SCOUT_FINDINGS_DISPLAY_LIMIT);
    expect(view.findings[0]).toHaveLength(LOG_TRUNC_200);
    expect(view).toMatchObject({ status: "done", task: "investigate" });
  });

  it("projects a failed scout commission with error", () => {
    const view = scoutView({ success: false, task: "x", error: "scout disabled" });
    expect(view).toMatchObject({ success: false, findings: [], error: "scout disabled" });
  });
});

describe("system/tool views", () => {
  it("projects a successful system execution", () => {
    const view = systemView({
      success: true,
      command: "ls",
      output: "a.txt",
      stderr: "",
      returncode: 0,
    });
    expect(view).toMatchObject({
      success: true,
      type: "system",
      command: "ls",
      output: "a.txt",
      returncode: 0,
    });
    expect(view.timed_out).toBeUndefined();
    expect(view.error).toBeUndefined();
  });

  it("projects timeout and error variants", () => {
    const timeoutView = systemView({ success: false, command: "x", timed_out: true, returncode: null });
    expect(timeoutView).toMatchObject({ success: false, timed_out: true });
    expect(timeoutView.error).toBeUndefined();
    expect(systemView({ success: false, command: "x", error: "shell not found" })).toMatchObject({
      error: "shell not found",
    });
  });

  it("projects a tool result with data and args", () => {
    const view = toolResultView({
      success: true,
      tool: "read_file",
      args: { path: "a.txt" },
      data: { content: "x" },
    });
    expect(view).toMatchObject({
      success: true,
      type: "tool",
      tool: "read_file",
      args: { path: "a.txt" },
      data: { content: "x" },
    });
  });

  it("projects a failed tool call with error and null-safe data", () => {
    const view = toolResultView({ success: false, tool: "nope", error: "unknown tool" });
    expect(view).toMatchObject({ success: false, error: "unknown tool", data: null, args: {} });
  });
});