/**
 * Selector / completer / command-group tests.
 *
 * Selector and completer are pure local logic; command groups register
 * handlers that route through a fake bridge (host stays the authority).
 */

import { describe, expect, it } from "vitest";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { ProtocolBridge, type Transport } from "../src/engine/bridge.ts";
import { encodeMessage, makeMessage } from "../src/protocol/wire-envelope.ts";
import {
  INJECTION_HIGH_RISK_THRESHOLD,
  INJECTION_MEDIUM_RISK_THRESHOLD,
  preconnectImpact,
  preselect,
  riskLevelOf,
  selectByAgentId,
  selectByRole,
  toRoster,
} from "../src/engine/agent-selector.ts";
import { parseCommandCatalog } from "../src/engine/command-catalog.ts";
import { BUILTIN_COMMANDS, Completer, DEFAULT_ALIASES } from "../src/engine/command-completion.ts";
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

describe("preconnect impact projection", () => {
  it("grades risk levels at the reference thresholds", () => {
    // INJECTION_*_THRESHOLD in kernel params/agent.py: medium 0.3, high 0.7
    expect(INJECTION_MEDIUM_RISK_THRESHOLD).toBe(0.3);
    expect(INJECTION_HIGH_RISK_THRESHOLD).toBe(0.7);
    expect(riskLevelOf(0)).toBe("none");
    expect(riskLevelOf(0.3)).toBe("none"); // strictly greater than threshold
    expect(riskLevelOf(0.31)).toBe("medium");
    expect(riskLevelOf(0.7)).toBe("medium");
    expect(riskLevelOf(0.71)).toBe("high");
  });

  it("projects an allowed preconnect with no risk", () => {
    const impact = preconnectImpact({ allowed: true, reason: "ok", injection_risk: 0 });
    expect(impact).toEqual({
      allowed: true,
      reason: "ok",
      risk: 0,
      riskLevel: "none",
      label: "selector.risk.none",
    });
  });

  it("projects a denied preconnect with a risk label", () => {
    const impact = preconnectImpact({
      allowed: false,
      reason: "prompt_injection_suspected",
      injection_risk: 0.8342,
    });
    expect(impact).toEqual({
      allowed: false,
      reason: "prompt_injection_suspected",
      risk: 0.83,
      riskLevel: "high",
      label: "selector.denied",
    });
  });

  it("defaults missing host fields safely", () => {
    const impact = preconnectImpact({});
    expect(impact).toEqual({
      allowed: false,
      reason: "",
      risk: 0,
      riskLevel: "none",
      label: "selector.denied",
    });
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

  it("merges command catalog names and aliases into candidates", () => {
    const catalog = parseCommandCatalog("agents:\n  help: \"h\"\n  aliases: [\"ls\"]");
    const c = new Completer({ catalog });
    const names = c.candidates();
    expect(names).toContain("agents");
    expect(names).toContain("ls");
    expect(c.complete("age")).toEqual(["agents"]);
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

    for (const name of [
      "settings", "settings-set", "status", "memory-digest", "model-specs", "cells",
      "card-submit", "card-approve", "l3a-send", "tool-invoke",
    ]) {
      expect(dispatcher.has(name)).toBe(true);
    }

    const out = await dispatcher.dispatch({ name: "status", args: [] }, { sessionId: "s-1" });
    expect(out.kind).toBe("local");
    expect((out as { data: { messages: unknown[] } }).data.messages).toHaveLength(1);
    // The request went over the wire to the host — one line per command.
    expect(received).toHaveLength(1);
    expect(received[0]).toContain('"name":"status"');
  });

  it("card/l3a/tool groups forward to the host with proper payloads", async () => {
    const dispatcher = new Dispatcher();
    const { bridge, received } = fakeHost();
    registerCommandGroups(dispatcher, { bridge });

    await dispatcher.dispatch({ name: "card-submit", args: ["card: v1"] }, { sessionId: "s-1" });
    await dispatcher.dispatch({ name: "card-approve", args: ["c42"] }, { sessionId: "s-1" });
    await dispatcher.dispatch({ name: "l3a-send", args: ["do work"] }, { sessionId: "s-1" });
    await dispatcher.dispatch({ name: "tool-invoke", args: ["search", "{}"] }, { sessionId: "s-1" });
    expect(received).toHaveLength(4);
    expect(received[0]).toContain('"name":"card_submit"');
    expect(received[1]).toContain('"name":"card_approve"');
    expect(received[2]).toContain('"name":"l3a_send"');
    expect(received[3]).toContain('"name":"tool_invoke"');
  });

  it("card/l3a/tool groups validate arity locally before bridging", async () => {
    const dispatcher = new Dispatcher();
    const { bridge, received } = fakeHost();
    registerCommandGroups(dispatcher, { bridge });
    for (const [name, args] of [
      ["card-submit", []],
      ["card-approve", []],
      ["l3a-send", []],
      ["tool-invoke", ["search"]],
    ] as const) {
      const out = await dispatcher.dispatch({ name, args: [...args] }, { sessionId: "s-1" });
      expect(out).toMatchObject({ kind: "local", data: { success: false } });
    }
    expect(received).toHaveLength(0); // nothing crossed the wire
  });

  it("settings-set validates arity locally before bridging", async () => {
    const dispatcher = new Dispatcher();
    const { bridge } = fakeHost();
    registerCommandGroups(dispatcher, { bridge });
    const out = await dispatcher.dispatch({ name: "settings-set", args: ["only-key"] }, { sessionId: "s-1" });
    expect(out).toMatchObject({ kind: "local", data: { success: false } });
  });
});
