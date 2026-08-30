/**
 * TerminalRenderer tests — deterministic, frontend-neutral output records.
 */

import { describe, expect, it } from "vitest";
import { I18n } from "../src/i18n/locale-catalog.ts";
import { makeMessage, type Message } from "../src/protocol/wire-envelope.ts";
import type { TerminalRunResult } from "../src/engine/terminal-shell.ts";
import {
  LOG_TRUNC_100,
  LOG_TRUNC_200,
  TerminalRenderer,
  TOOL_RESULT_DISPLAY_LIMIT,
  renderTerminalBanner,
} from "../src/engine/terminal-renderer.ts";

function local(data: Record<string, unknown>, success = true): TerminalRunResult {
  return {
    success,
    type: "local",
    route: { kind: "engine", name: String(data.type ?? "local"), args: [] },
    data,
    responses: [],
    elapsedMs: 0,
  };
}

function bridged(messages: Message[], success = true): TerminalRunResult {
  return {
    success,
    type: "bridge",
    route: { kind: "bridge", name: "result", args: [] },
    responses: messages,
    elapsedMs: 0,
  };
}

describe("TerminalRenderer", () => {
  it("renders a detached banner with the local i18n dictionary", () => {
    const frame = renderTerminalBanner();
    expect(frame).toMatchObject({ success: true, type: "banner" });
    expect(frame.lines.map((line) => line.text)).toEqual([
      "Agent OS Terminal — Type 'help' for commands, 'exit' to quit",
      "/intent <text>  → L3A direct session",
      "/intent <text>@<cell>/<agent> → Route to specific Cell/Agent",
      "/scout <task>  → Scout investigation",
      "$ <command>  → Raw system command (Bash/PowerShell)",
      "<tool> <args>  → Tool execution (aliases: rf→read_file)",
      "",
    ]);
  });

  it("renders help and tools payloads with stable columns", () => {
    const renderer = new TerminalRenderer();
    const help = renderer.render(
      local({
        success: true,
        type: "help",
        commands: [{ name: "help", help: "Show commands" }],
        more: 2,
      }),
    );
    expect(help.lines.map((line) => line.text)).toEqual([
      "Commands:",
      "  help                 Show commands",
      "... and 2 more tools (type 'tools' to list all)",
    ]);

    const tools = renderer.render(
      local({
        success: true,
        type: "tools",
        tools: [{ name: "grep", description: "Search text" }],
        total: 1,
      }),
    );
    expect(tools.lines.map((line) => line.text)).toEqual(["  grep                      Search text", "Total: 1 tools"]);

    const dispatcherHelp = renderer.render({
      ...local({ success: true, commands: ["help", "status"] }),
      route: { kind: "engine", name: "help", args: [] },
    });
    expect(dispatcherHelp.lines.map((line) => line.text)).toEqual([
      "Commands:",
      "  help                ",
      "  status              ",
      "... and 0 more tools (type 'tools' to list all)",
    ]);
  });

  it("renders intent and scout success/error variants", () => {
    const renderer = new TerminalRenderer({ i18n: new I18n() });
    expect(
      renderer.render(
        local({
          success: true,
          type: "intent",
          card_id: "c-1",
          domain: "ops",
          agent: "writer",
          card_type: "card",
        }),
      ).lines.map((line) => line.text),
    ).toEqual(["[L3A] Card: c-1", "        Domain: ops", "        Agent: writer", "        Type: card"]);

    const failed = renderer.render(local({ success: false, type: "intent", error: "parse failed" }, false));
    expect(failed.lines).toEqual([{ role: "error", text: "[L3A] Error: parse failed" }]);

    const scout = renderer.render(
      local({
        success: true,
        type: "scout",
        status: "done",
        findings: ["one", "two"],
      }),
    );
    expect(scout.lines.map((line) => line.text)).toEqual([
      "[Scout] Status: done",
      "[Scout] Findings (2):",
      "    - one",
      "    - two",
    ]);
  });

  it("renders system output, stderr, exit, and timeout without performing execution", () => {
    const renderer = new TerminalRenderer();
    const system = renderer.render(
      bridged([
        makeMessage("s", 1, "ack", { ack_seq: 1 }),
        makeMessage("s", 2, "result", {
          success: true,
          type: "system",
          output: "a\nb",
          stderr: "warn",
          returncode: 0,
        }),
      ]),
    );
    expect(system.lines.map((line) => line.text)).toEqual(["  a", "  b", "[stderr] warn", "[Exit] 0"]);

    const timeout = renderer.render(
      local({ success: false, type: "system", command: "x", timed_out: true, returncode: null }, false),
    );
    expect(timeout.lines).toEqual([{ role: "error", text: "[Error] Command timed out after ?s" }]);
  });

  it("renders sorted, bounded tool fields and generic errors", () => {
    const renderer = new TerminalRenderer({ fieldLimit: 2 });
    const tool = renderer.render(
      local({
        success: true,
        type: "tool",
        data: { z: "last", a: "first", m: "omitted" },
      }),
    );
    expect(tool.lines.map((line) => line.text)).toEqual(["  a: first", "  m: omitted"]);

    const long = "x".repeat(LOG_TRUNC_100 + 10);
    const generic = renderer.render(
      local({ success: true, output: long, answer: "ignored" }),
    );
    expect(generic.lines[0].text).toHaveLength(LOG_TRUNC_100 + 10);
    expect(generic.lines[0].text.length).toBeLessThanOrEqual(LOG_TRUNC_200);

    const failed = renderer.render(
      local({ success: false, error: "denied", suggestions: ["help", "status"] }, false),
    );
    expect(failed.lines).toEqual([
      { role: "error", text: "[Error] denied" },
      { role: "output", text: "  help, status" },
    ]);
    expect(TOOL_RESULT_DISPLAY_LIMIT).toBe(5);
  });

  it("renders bounded history and exposes plain text for simple frontends", () => {
    const renderer = new TerminalRenderer({ historyLimit: 1 });
    const result: TerminalRunResult = {
      success: true,
      type: "history",
      route: { kind: "engine", name: "history", args: [] },
      responses: [],
      entries: [
        { seq: 3, timestamp: "2026-08-30T00:00:00.000Z", input: "$ three", name: "__system", elapsedMs: 1 },
        { seq: 2, timestamp: "2026-08-30T00:00:00.000Z", input: "$ two", name: "__system", elapsedMs: 1 },
      ],
      elapsedMs: 0,
    };
    expect(renderer.renderText(result)).toEqual(["    3  $ three"]);
  });

  it("ignores control acknowledgements and keeps empty results side-effect free", () => {
    const renderer = new TerminalRenderer();
    const empty: TerminalRunResult = {
      success: true,
      type: "empty",
      route: { kind: "empty" },
      responses: [],
      elapsedMs: 0,
    };
    expect(renderer.render(empty).lines).toEqual([]);
    expect(
      renderer.render(
        bridged([makeMessage("s", 1, "ack", { ack_seq: 1 })]),
      ).lines,
    ).toEqual([]);
  });
});
