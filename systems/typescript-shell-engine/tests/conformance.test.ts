import { describe, it, expect } from "vitest";
import {
  decodeMessage, validateMessage, makeMessage,
  Outbox,
} from "../src/wire-envelope.ts";
import { HOST_DERIVED_FIELDS } from "../src/wire-types.ts";
import { parseRoute, splitArgs } from "../src/engine/route.ts";
import { ProtocolBridge } from "../src/engine/bridge.ts";
import type { Message } from "../src/wire-envelope.ts";

function baseEnvelope(kind: string, payload: Record<string, unknown>) {
  return { v: 1, session_id: "s-1", seq: 1, ts: 0.0, kind, payload };
}

describe("conformance R3: ts must be a finite number", () => {
  it("rejects NaN and Infinity timestamps", () => {
    expect(validateMessage({ ...baseEnvelope("intent", { text: "hi" }), ts: NaN })).not.toHaveLength(0);
    expect(validateMessage({ ...baseEnvelope("intent", { text: "hi" }), ts: Infinity })).not.toHaveLength(0);
    expect(validateMessage(baseEnvelope("intent", { text: "hi" }))).toHaveLength(0);
  });
});

describe("conformance R4: host-derived authorization fields are banned", () => {
  it("rejects command payloads carrying banned fields", () => {
    for (const field of HOST_DERIVED_FIELDS) {
      const msg = baseEnvelope("command", { name: "__system", args: ["ls"], [field]: true });
      const decoded = decodeMessage(JSON.stringify(msg));
      expect(decoded.error).toContain("host-derived authorization fields");
      expect(decoded.message).toBeNull();
    }
  });

  it("rejects control payloads carrying banned fields", () => {
    const msg = baseEnvelope("control", { op: "attach", pre_approved: true });
    const decoded = decodeMessage(JSON.stringify(msg));
    expect(decoded.error).toContain("host-derived authorization fields");
  });

  it("still accepts ring/danger declarations (gate inputs, no authority)", () => {
    const msg = baseEnvelope("command", { name: "__system", args: ["ls"], ring: 2, danger: 2 });
    const decoded = decodeMessage(JSON.stringify(msg));
    expect(decoded.message).not.toBeNull();
  });
});

describe("conformance R6: dialect routing order and quote-aware splitting", () => {
  it("classifies $ before pipeline", () => {
    expect(parseRoute("$echo a|b")).toEqual({ kind: "system", command: "echo a|b" });
  });

  it("classifies / before pipeline so pipe args stay intact", () => {
    const r = parseRoute("/search a|b");
    expect(r).toEqual({ kind: "engine", name: "search", args: ["a|b"] });
  });

  it("keeps quoted pipes inside one argument", () => {
    const r = parseRoute('/search "a|b" c');
    expect(r.kind === "engine" && r.args).toEqual(["a|b", "c"]);
  });

  it("still detects unquoted pipelines after engine/system checks", () => {
    const r = parseRoute("status | format json");
    expect(r.kind).toBe("pipeline");
  });

  it("splitArgs handles quotes, escapes and whitespace", () => {
    expect(splitArgs('say "hello world"')).toEqual(["say", "hello world"]);
    expect(splitArgs("a\\ b c")).toEqual(["a b", "c"]);
  });
});

describe("conformance R1: non-destructive outbox ack and recovery", () => {
  it("one ack never erases another view's replay window", () => {
    const box = new Outbox(4);
    const m = (seq: number): Message =>
      makeMessage("s-1", seq, "event", { event_type: "e", data: {} });
    for (const seq of [1, 2, 3]) box.append(m(seq));
    box.ack(2);
    // Non-destructive: items retained; replay after cursor skips acked.
    expect(box.size).toBe(3);
    expect(box.unacked().map((x) => x.seq)).toEqual([3]);
    // Explicit recovery from -1 still sees the full retained window.
    expect(box.unacked(-1).map((x) => x.seq)).toEqual([1, 2, 3]);
  });
});

describe("bridge: undecodable responses surface as errors (R7 twin)", () => {
  it("throws on garbage transport lines instead of dropping them", async () => {
    const ok = JSON.stringify({
      v: 1, session_id: "s-1", seq: 7, ts: 1.0, kind: "result",
      payload: { success: true },
    });
    const bridge = new ProtocolBridge({
      sessionId: "s-1",
      transport: async () => ["{not json", ok],
    });
    await expect(bridge.command("status")).rejects.toThrow(/undecodable response/);
  });

  it("reports round-trip telemetry when a sink is configured", async () => {
    const events: Array<{ label: string; responseCount: number }> = [];
    const reply = JSON.stringify({
      v: 1, session_id: "s-1", seq: 7, ts: 1.0, kind: "result",
      payload: { success: true },
    });
    const bridge = new ProtocolBridge({
      sessionId: "s-1",
      transport: async () => [reply],
      onTelemetry: (e) => events.push({ label: e.label, responseCount: e.responseCount }),
    });
    await bridge.command("status");
    expect(events).toEqual([{ label: "command:status", responseCount: 1 }]);
  });
});
