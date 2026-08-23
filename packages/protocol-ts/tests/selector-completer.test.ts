/**
 * Selector / completer / command-group tests.
 *
 * Selector and completer are pure local logic; command groups register
 * handlers that route through a fake bridge (host stays the authority).
 */

import { describe, expect, it } from "vitest";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { ProtocolBridge, type Transport } from "../src/engine/bridge.ts";
import { encodeMessage, makeMessage } from "../src/envelope.ts";
import { preselect, selectByAgentId, selectByRole, toRoster } from "../src/engine/selector.ts";
import { BUILTIN_COMMANDS, Completer, DEFAULT_ALIASES } from "../src/engine/completer.ts";
import { registerCommandGroups } from "../src/engine/command-groups.ts";

const LIVENESS_A = {
  agents: {
    "agent-1": { role: "scout", status: "running", alive: true },
    "agent-2": { role: "editor", status: "idle", alive: false },
  },
  territory: ["code", "docs"],
};

const LIVENESS_B = {
  agents: {
    "agent-3": { role: "scout", status: "running", alive: true },
  },
  territory: ["ops"],
};

describe("selector projection", () => {
  it("converts liveness dicts into roster entries", () => {
    const roster = toRoster(LIVENESS_A);
    expect(roster).toHaveLength(2);
    expect(roster[0]).toMatchObject({ agent_id: "agent-1", role: "scout", alive: true });
  });

  it("preselect aggregates cells and totals", () => {
    const out = preselect({ "cell-a": LIVENESS_A, "cell-b": LIVENESS_B });
    expect(out.cells).toEqual(["cell-a", "cell-b"]);
    expect(out.total).toBe(3);
  });

  it("selectByAgentId finds an agent or reports an error", () => {
    // cell_id is injected by preselect (mirrors Python preselect); use it to
    // build a cross-cell roster rather than calling toRoster bare.
    const roster = preselect({ "cell-a": LIVENESS_A, "cell-b": LIVENESS_B }).agents;
    const hit = selectByAgentId(roster, "agent-3");
    expect(hit.success).toBe(true);
    expect(hit.cell_id).toBe("cell-b");
    const miss = selectByAgentId(roster, "nope");
    expect(miss.success).toBe(false);
    expect(miss.error).toContain("unknown agent");
  });

  it("selectByRole matches case-insensitively and respects cell filter", () => {
    const roster = preselect({ "cell-a": LIVENESS_A, "cell-b": LIVENESS_B }).agents;
    const hit = selectByRole(roster, "SCOUT");
    expect(hit.success).toBe(true);
    expect(hit.agent_id).toBe("agent-1");
    const cellHit = selectByRole(roster, "scout", "cell-b");
    expect(cellHit.agent_id).toBe("agent-3");
    expect(selectByRole(roster, "ghost").success).toBe(false);
  });
});

describe("completer", () => {
  it("candidates merge tools, builtins and aliases, sorted", () => {
    const c = new Completer({ toolNames: ["grep", "read_file"] });
    const names = c.candidates();
    expect(names).toContain("grep");
    expect(names).toContain("help");
    expect(names).toContain("rf");
    expect(names).toEqual([...names].sort());
    expect(names).toHaveLength(new Set(names).size);
  });

  it("prefix-matches command tokens before a space", () => {
    const c = new Completer({ toolNames: ["list_directory"] });
    expect(c.complete("lis")).toEqual(["list_directory"]);
    expect(c.complete("z")).toEqual([]);
  });

  it("offers filesystem partials after a space", () => {
    const c = new Completer();
    expect(c.complete("read_file /")).toEqual(["/"]);
    expect(c.complete("cat .")).toContain(".");
  });

  it("exposes the builtin list and default aliases", () => {
    expect(BUILTIN_COMMANDS).toContain("help");
    expect(DEFAULT_ALIASES.rf).toBe("read_file");
  });
});

describe("command groups", () => {
  function fakeHost(): { received: string[]; bridge: ProtocolBridge } {
    const received: string[] = [];
    const transport: Transport = async (line) => {
      received.push(line);
      // Host answers any command with a success result envelope.
      return [
        encodeMessage(makeMessage("s-1", 200, "result", { success: true, name: "host-ok" }, "", 0)),
      ];
    };
    return { received, bridge: new ProtocolBridge({ sessionId: "s-1", transport }) };
  }

  it("registers all command groups and routes to the bridge", async () => {
    const dispatcher = new Dispatcher();
    const { bridge, received } = fakeHost();
    registerCommandGroups(dispatcher, { bridge });

    for (const name of ["settings", "settings-set", "status", "memory-digest", "model-specs", "cells"]) {
      expect(dispatcher.has(name)).toBe(true);
    }

    const out = await dispatcher.dispatch({ name: "status", args: [] }, { sessionId: "s-1" });
    expect(out.kind).toBe("local");
    expect((out as { data: { messages: unknown[] } }).data.messages).toHaveLength(1);
    // The request went over the wire to the host — one line per command.
    expect(received).toHaveLength(1);
    expect(received[0]).toContain('"name":"status"');
  });

  it("settings-set validates arity locally before bridging", async () => {
    const dispatcher = new Dispatcher();
    const { bridge } = fakeHost();
    registerCommandGroups(dispatcher, { bridge });
    const out = await dispatcher.dispatch({ name: "settings-set", args: ["only-key"] }, { sessionId: "s-1" });
    expect(out).toMatchObject({ kind: "local", data: { success: false } });
  });
});
