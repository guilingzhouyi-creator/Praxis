/**
 * TerminalShell tests — dialect routing, bridge delegation and bounded history.
 */

import { describe, expect, it } from "vitest";
import { decodeMessage, encodeMessage, makeMessage, type Message } from "../src/protocol/wire-envelope.ts";
import { ProtocolBridge, type Transport } from "../src/engine/bridge.ts";
import { registerBuiltins } from "../src/engine/builtins.ts";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { ShellFamily } from "../src/engine/session-family.ts";
import { TerminalShell } from "../src/engine/terminal-shell.ts";

function fakeHost(received: string[]): Transport {
  return async (line: string) => {
    received.push(line);
    const message = decodeMessage(line).message;
    if (!message) return [];
    const payload = message.payload;
    const name = typeof payload.name === "string" ? payload.name : String(payload.op ?? message.kind);
    return [
      encodeMessage(
        makeMessage(message.session_id, message.seq, "result", { success: true, name, args: payload.args ?? [] }),
      ),
    ];
  };
}

function setup(historySize = 10): { shell: TerminalShell; received: string[] } {
  const received: string[] = [];
  const bridge = new ProtocolBridge({ sessionId: "s-1", transport: fakeHost(received) });
  const dispatcher = new Dispatcher();
  registerBuiltins(dispatcher);
  return { shell: new TerminalShell({ bridge, dispatcher, historySize }), received };
}

function outgoing(received: string[], index = received.length - 1): Message {
  return decodeMessage(received[index]).message!;
}

describe("TerminalShell", () => {
  it("registers as a ShellFamily dialect and exposes a pure classifier", () => {
    const { shell } = setup();
    const family = new ShellFamily();
    family.register(shell, ["tui"]);
    expect(family.resolve("tui")).toBe(shell);
    expect(shell.classify('/search "a|b"')).toEqual({
      kind: "engine",
      name: "search",
      args: ["a|b"],
    });
  });

  it("keeps local help local and records the input", async () => {
    const { shell, received } = setup();
    const result = await shell.run("help");
    expect(result).toMatchObject({ success: true, type: "local", route: { kind: "engine", name: "help" } });
    expect(result.responses).toEqual([]);
    expect(received).toHaveLength(0);
    expect(shell.snapshot().history_length).toBe(1);
  });

  it("forwards system and pipeline routes as host commands", async () => {
    const { shell, received } = setup();
    await shell.run("$ echo hello");
    expect(outgoing(received)).toMatchObject({
      kind: "command",
      payload: { name: "__system", args: ["echo hello"] },
    });

    await shell.run("status | format json");
    expect(outgoing(received)).toMatchObject({
      kind: "command",
      payload: { name: "__pipeline", args: ["status", "format json"] },
    });
  });

  it("routes bare text to L3A by default and tools in direct mode", async () => {
    const { shell, received } = setup();
    const intent = await shell.run("summarize the latest run");
    expect(intent).toMatchObject({ type: "l3a", route: { kind: "l3a", text: "summarize the latest run" } });
    expect(outgoing(received)).toMatchObject({
      kind: "command",
      payload: { name: "l3a_send", args: ["summarize the latest run", "s-1"] },
    });

    shell.switchToDirect("cell-a", "agent-a");
    const tool = await shell.run("read_file path=a.txt");
    expect(tool).toMatchObject({ type: "bridge", route: { kind: "bridge", name: "read_file" } });
    expect(outgoing(received)).toMatchObject({
      kind: "command",
      payload: { name: "read_file", args: ["path=a.txt"] },
    });
  });

  it("keeps terminal conveniences on the bridge boundary", async () => {
    const { shell, received } = setup();
    await shell.run("tools");
    expect(outgoing(received)).toMatchObject({ payload: { name: "tools", args: [] } });
    await shell.run("status");
    expect(outgoing(received)).toMatchObject({ payload: { name: "agent_status", args: [] } });
  });

  it("returns bounded, detached command history", async () => {
    const { shell } = setup(2);
    await shell.run("$ one");
    await shell.run("$ two");
    await shell.run("$ three");
    expect(shell.snapshot().history_length).toBe(2);
    expect(shell.recentHistory().map((entry) => entry.input)).toEqual(["$ three", "$ two"]);

    const view = await shell.run("history");
    expect(view.type).toBe("history");
    expect(view.entries?.map((entry) => entry.input)).toEqual(["$ three", "$ two"]);
    expect(shell.snapshot().history_length).toBe(2);
  });

  it("creates isolated sessions without changing the default session", () => {
    const { shell } = setup();
    const other = shell.createSession("s-2");
    other.switchToDirect("cell-b", "agent-b");
    expect(other.isDirect()).toBe(true);
    expect(shell.getSession().isDirect()).toBe(false);
    expect(shell.snapshot().session.session_id).toBe("s-1");
  });
});
