import { describe, it, expect } from "vitest";
import { ProtocolBridge, streamResponses } from "../src/engine/bridge.ts";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import {
  registerSettingsGroup, registerSystemGroup, registerMemoryGroup,
  registerModelGroup, registerSelectorGroup,
} from "../src/engine/command-groups.ts";
import { makeMessage } from "../src/protocol/wire-envelope.ts";

/** Recording transport: echoes one result envelope per request. */
function makeRecordingTransport(sessionId?: string) {
  const requests: { name: string; args: string[] }[] = [];
  let counter = 100;
  const transport = async (line: string): Promise<string[]> => {
    const parsed = JSON.parse(line) as { session_id?: string; payload?: { name?: string; args?: string[] } };
    const p = parsed?.payload ?? {};
    const effectiveSessionId = sessionId ?? parsed?.session_id ?? "sess";
    if (typeof p.name === "string") {
      requests.push({ name: p.name, args: (p.args as string[]) ?? [] });
      const reply = makeMessage(effectiveSessionId, counter++, "event", { ok: true, echo: p.name });
      return [JSON.stringify(reply)];
    }
    return [];
  };
  return { transport, requests };
}

function makeBridge() {
  const { transport, requests } = makeRecordingTransport();
  const bridge = new ProtocolBridge({ sessionId: "sess", transport });
  return { bridge, requests };
}

describe("ProtocolBridge domain helpers", () => {
  it("settings domain sends settings_get/settings_set with JSON value", async () => {
    const { bridge, requests } = makeBridge();
    await bridge.settingsGet("theme");
    await bridge.settingsSet("theme", { dark: true });
    expect(requests[0]).toEqual({ name: "settings_get", args: ["theme"] });
    expect(requests[1]).toEqual({ name: "settings_set", args: ["theme", '{"dark":true}'] });
  });

  it("settingsGet without key sends empty args", async () => {
    const { bridge, requests } = makeBridge();
    await bridge.settingsGet();
    expect(requests[0].args).toEqual([]);
  });

  it("memory domain covers digest/recall/remember with limit and ring", async () => {
    const { bridge, requests } = makeBridge();
    await bridge.memoryDigest();
    await bridge.memoryRecall("error patterns", 5);
    await bridge.memoryRemember("insight", "use ring buffer", 3);
    expect(requests.map((r) => r.name)).toEqual(["memory_digest", "memory_recall", "memory_remember"]);
    expect(requests[1].args).toEqual(["error patterns", "5"]);
    expect(requests[2].args).toEqual(["insight", "use ring buffer", "3"]);
  });

  it("system/model domains send status/health/model_specs/model_switch", async () => {
    const { bridge, requests } = makeBridge();
    await bridge.systemStatus();
    await bridge.healthCheck();
    await bridge.modelSpecs();
    await bridge.modelSwitch("openai", "gpt-5");
    expect(requests.map((r) => r.name)).toEqual(["status", "health", "model_specs", "model_switch"]);
    expect(requests[3].args).toEqual(["openai", "gpt-5"]);
  });

  it("selector/card/l3a/tool domains forward correct command names", async () => {
    const { bridge, requests } = makeBridge();
    await bridge.cellLiveness();
    await bridge.cardSubmit("card: v1");
    await bridge.cardApprove("c42");
    await bridge.l3aSend("do work");
    await bridge.l3aSend("do work", "session-9");
    await bridge.toolInvoke("search", '{"q":"x"}');
    expect(requests.map((r) => r.name)).toEqual([
      "cell_liveness", "card_submit", "card_approve", "l3a_send", "l3a_send", "tool_invoke",
    ]);
    expect(requests[4].args).toEqual(["do work", "session-9"]);
    expect(requests[5].args).toEqual(["search", '{"q":"x"}']);
  });

  it("control plane: attach/ack/replay include optional view_id", async () => {
    const { bridge } = makeBridge();
    const seen: Record<string, unknown>[] = [];
    const raw = (bridge as unknown as { opts: { transport: (l: string) => Promise<string[]> } }).opts.transport;
    const spy = async (line: string) => {
      seen.push(JSON.parse(line) as Record<string, unknown>);
      return [];
    };
    (bridge as unknown as { opts: { transport: (l: string) => Promise<string[]> } }).opts.transport = spy;
    void raw;
    await bridge.attach("s2");
    await bridge.attach("s2", "view-web");
    await bridge.detach("s2");
    await bridge.detach("s2", "view-web");
    await bridge.ack(7);
    await bridge.ack(7, "view-tui");
    await bridge.resume("s3", undefined, -1);
    await bridge.replay("s2", undefined, -1);
    await bridge.replay("s2", "view-cli", 4);
    const kinds = seen.map((m) => (m as { kind: string }).kind);
    expect(kinds).toEqual(["control", "control", "control", "control", "ack", "ack", "control", "control", "control"]);
    const payloads = seen.map((m) => m.payload as Record<string, unknown>);
    expect(payloads[1]).toHaveProperty("view_id", "view-web");
    expect(payloads[2]).toMatchObject({ op: "detach", session_id: "s2" });
    expect(payloads[3]).toMatchObject({ op: "detach", session_id: "s2", view_id: "view-web" });
    expect(payloads[4]).toEqual({ ack_seq: 7 });
    expect(payloads[5]).toEqual({ ack_seq: 7, view_id: "view-tui" });
    expect(payloads[6]).toMatchObject({ op: "resume", session_id: "s3", last_acked: -1 });
    expect(payloads[8]).toMatchObject({ op: "recovery", session_id: "s2", last_acked: 4, view_id: "view-cli" });
    expect(seen[0].session_id).toBe("s2");
    expect(seen[4].session_id).toBe("sess");
    expect(seen[6].session_id).toBe("s3");
  });

  it("batch preserves command order", async () => {
    const { bridge, requests } = makeBridge();
    const results = await bridge.batch([
      { name: "status" }, { name: "health" }, { name: "memory_digest", args: ["x"] },
    ]);
    expect(results).toHaveLength(3);
    expect(requests.map((r) => r.name)).toEqual(["status", "health", "memory_digest"]);
  });

  it("stream yields decoded messages from transport responses", async () => {
    const { bridge } = makeBridge();
    const got: string[] = [];
    for await (const msg of bridge.stream("command", { name: "status", args: [] })) {
      got.push(String((msg.payload as { echo?: string }).echo));
    }
    expect(got).toEqual(["status"]);
  });

  it("maxSeq wraps around after exceeding the bound", async () => {
    const { transport } = makeRecordingTransport();
    const bridge = new ProtocolBridge({ sessionId: "s", transport, maxSeq: 2 });
    await bridge.command("a"); // seq 1
    await bridge.command("b"); // seq 2
    await bridge.command("c"); // wraps to seq 1
    const lines: number[] = [];
    const b2 = new ProtocolBridge({
      sessionId: "s", maxSeq: 2,
      transport: async (line) => { lines.push((JSON.parse(line) as { seq: number }).seq); return []; },
    });
    await b2.command("x"); await b2.command("y"); await b2.command("z");
    expect(lines).toEqual([1, 2, 1]);
  });

  it("rejects invalid maxSeq at construction", () => {
    const { transport } = makeRecordingTransport();
    expect(() => new ProtocolBridge({ sessionId: "s", transport, maxSeq: 0 })).toThrow("maxSeq");
    expect(() => new ProtocolBridge({ sessionId: "s", transport, maxSeq: 1.5 })).toThrow("maxSeq");
    expect(() => new ProtocolBridge({ sessionId: "s", transport, maxSeq: Number.MAX_SAFE_INTEGER + 1 })).toThrow("safe");
  });
});

describe("streamResponses standalone generator", () => {
  it("yields only valid envelopes, skipping decode failures", async () => {
    const good = JSON.stringify(makeMessage("s", 1, "event", { ok: true }));
    const transport = async () => [good, "{broken json", "not even close"];
    const got: unknown[] = [];
    for await (const m of streamResponses(transport, "")) got.push(m);
    expect(got).toHaveLength(1);
  });
});

describe("command groups registration through real Dispatcher", () => {
  function wired() {
    const { bridge, requests } = makeBridge();
    const d = new Dispatcher();
    registerSettingsGroup(d, { bridge });
    registerSystemGroup(d, { bridge });
    registerMemoryGroup(d, { bridge });
    registerModelGroup(d, { bridge });
    registerSelectorGroup(d, { bridge });
    return { d, requests };
  }

  it("registers and dispatches all five domains to bridge commands", async () => {
    const { d, requests } = wired();
    for (const cmd of ["settings", "status", "memory-digest", "model-specs", "cells"]) {
      expect(d.has(cmd)).toBe(true);
      await d.dispatch({ name: cmd, args: [] }, { sessionId: "sess" });
    }
    expect(requests.map((r) => r.name)).toEqual([
      "settings_get", "status", "memory_digest", "model_specs", "cell_liveness",
    ]);
  });

  it("each handler returns local results tagged by domain", async () => {
    const { d } = wired();
    const res = await d.dispatch({ name: "status", args: [] }, { sessionId: "sess" });
    expect(res).toMatchObject({ kind: "local", data: { domain: "system" } });
  });
});
