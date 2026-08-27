import { describe, it, expect, vi } from "vitest";
import { createL3Bridge } from "../src/engine/l3-bridge-interface.ts";
import type { ProtocolBridge } from "../src/engine/bridge.ts";
import { sanitizePayload, containsCoT, ALLOWED_PAYLOAD_KEYS } from "../src/engine/cot-guard.ts";
import { OutputGuard } from "../src/engine/output-policy.ts";
import { parseLine } from "../src/engine/parser.ts";

/** Recording fake bridge capturing (name, args) per call. */
function recordingFake() {
  const calls: Array<{ name: string; args: string[] }> = [];
  const fake = {
    settingsGet: (key = "") => { calls.push({ name: "settings_get", args: [key] }); return Promise.resolve([]); },
    settingsSet: (key: string, value: unknown) => { calls.push({ name: "settings_set", args: [key, JSON.stringify(value)] }); return Promise.resolve([]); },
    memoryDigest: () => { calls.push({ name: "memory_digest", args: [] }); return Promise.resolve([]); },
    memoryRecall: (q: string, limit = 10) => { calls.push({ name: "memory_recall", args: [q, String(limit)] }); return Promise.resolve([]); },
    memoryRemember: (t: string, c: string, ring = 2) => { calls.push({ name: "memory_remember", args: [t, c, String(ring)] }); return Promise.resolve([]); },
    systemStatus: () => { calls.push({ name: "status", args: [] }); return Promise.resolve([]); },
    healthCheck: () => { calls.push({ name: "health", args: [] }); return Promise.resolve([]); },
    modelSpecs: () => { calls.push({ name: "model_specs", args: [] }); return Promise.resolve([]); },
    modelSwitch: (p: string, m: string) => { calls.push({ name: "model_switch", args: [p, m] }); return Promise.resolve([]); },
    cellLiveness: () => { calls.push({ name: "cell_liveness", args: [] }); return Promise.resolve([]); },
    cardSubmit: (y: string) => { calls.push({ name: "card_submit", args: [y] }); return Promise.resolve([]); },
    cardApprove: (id: string) => { calls.push({ name: "card_approve", args: [id] }); return Promise.resolve([]); },
    l3aSend: (text: string, sid?: string) => { calls.push({ name: "l3a_send", args: sid ? [text, sid] : [text] }); return Promise.resolve([]); },
    toolInvoke: (n: string, p: string) => { calls.push({ name: "tool_invoke", args: [n, p] }); return Promise.resolve([]); },
  } as unknown as ProtocolBridge;
  return { bridge: createL3Bridge(fake), calls };
}

describe("IL3Bridge full domain routing", () => {
  it("routes every domain method to the exact python command with default args", async () => {
    const { bridge, calls } = recordingFake();
    await bridge.settings.get();
    await bridge.settings.set("k", { nested: true });
    await bridge.memory.digest();
    await bridge.memory.recall("q");
    await bridge.memory.remember("insight", "content");
    await bridge.system.status();
    await bridge.system.health();
    await bridge.model.specs();
    await bridge.model.switch("vendor", "model-x");
    await bridge.selector.cellLiveness();
    await bridge.card.submit("yaml-body");
    await bridge.card.approve("cid");
    await bridge.l3a.send("hello");
    await bridge.l3a.send("hello", "sid-7");
    await bridge.tool.invoke("grep", "{}");
    expect(calls.map((c) => `${c.name}(${c.args.join(",")})`)).toEqual([
      "settings_get()",
      'settings_set(k,{"nested":true})',
      "memory_digest()",
      "memory_recall(q,10)",
      "memory_remember(insight,content,2)",
      "status()",
      "health()",
      "model_specs()",
      "model_switch(vendor,model-x)",
      "cell_liveness()",
      "card_submit(yaml-body)",
      "card_approve(cid)",
      "l3a_send(hello)",
      "l3a_send(hello,sid-7)",
      "tool_invoke(grep,{})",
    ]);
  });

  it("never embeds domain logic — all wrappers stay thin", async () => {
    const { bridge } = recordingFake();
    for (const domain of Object.values(bridge)) {
      for (const fn of Object.values(domain)) {
        expect(fn.toString().length).toBeLessThan(200);
      }
    }
  });
});

describe("CoT privacy guards (P2.3)", () => {
  it("sanitizePayload strips forbidden reasoning keys at any depth", () => {
    const dirty = {
      result: "42",
      reasoning: "secret chain",
      nested: { thoughts: "inner leak", keep: 1 },
      arr: [{ cot: "leak" }, "plain"],
    };
    const clean = sanitizePayload(dirty);
    expect(clean).toEqual({ result: "42", nested: { keep: 1 }, arr: [{}, "plain"] });
  });

  it("containsCoT detects leakage without mutating input", () => {
    expect(containsCoT({ reasoning_content: "x" })).toBe(true);
    expect(containsCoT({ a: { deeper: [{ thinking: 1 }] } })).toBe(true);
    expect(containsCoT({ clean: "data" })).toBe(false);
  });

  it("ALLOWED_PAYLOAD_KEYS pins the per-kind contract surface", () => {
    expect(ALLOWED_PAYLOAD_KEYS.command.has("name")).toBe(true);
    expect(ALLOWED_PAYLOAD_KEYS.intent.has("text")).toBe(true);
    expect(ALLOWED_PAYLOAD_KEYS.ack.has("reasoning")).toBe(false);
  });
});

describe("OutputGuard display-safety mirror", () => {
  it("degrades to allow-through when no guard is registered", () => {
    const guard = new OutputGuard();
    const res = guard.guardOutput("agent-1", "raw response");
    expect(res).toEqual({ safe: true, output: "raw response" });
  });

  it("guard allow passes original output through", () => {
    const guard = new OutputGuard();
    guard.setGuard(() => ({ safe: true }));
    expect(guard.guardOutput("a", "fine")).toEqual({ safe: true, output: "fine" });
  });

  it("block with replacement swaps the text and flags unsafe", () => {
    const guard = new OutputGuard();
    guard.setGuard(() => ({ safe: false, replacement: "[blocked by policy]" }));
    const res = guard.guardOutput("a", "sensitive payload");
    expect(res.safe).toBe(false);
    expect(res.output).toBe("[blocked by policy]");
  });

  it("block without replacement truncates to LOG_TRUNC_100", () => {
    const guard = new OutputGuard();
    guard.setGuard(() => ({ safe: false }));
    const big = "y".repeat(5000);
    const res = guard.guardOutput("a", big);
    expect(res.safe).toBe(false);
    expect(res.output).toHaveLength(100);
  });

  it("a throwing callback degrades to allow-through (fail-open display)", () => {
    const guard = new OutputGuard();
    guard.setGuard(() => { throw new Error("callback bug"); });
    expect(guard.guardOutput("a", "kept")).toEqual({ safe: true, output: "kept" });
  });

  it("setGuard(undefined) clears an earlier registration", () => {
    const guard = new OutputGuard();
    guard.setGuard(() => ({ safe: false, replacement: "x" }));
    guard.setGuard(undefined);
    expect(guard.guardOutput("a", "clear again")).toEqual({ safe: true, output: "clear again" });
  });
});

describe("parser tokenization edges", () => {
  it("splits quoted arguments without shlex-style surprises", () => {
    const cmd = parseLine('deploy "prod cluster" --dry-run');
    expect(cmd.name).toBe("deploy");
    expect(cmd.args).toEqual(["prod cluster", "--dry-run"]);
  });

  it("returns empty result for blank lines", () => {
    expect(parseLine("").name).toBe("");
    expect(parseLine("   ").args).toEqual([]);
  });

  it("treats single quotes as literal characters (fast path split)", () => {
    const cmd = parseLine("echo 'a b' c");
    expect(cmd.args).toEqual(["'a", "b'", "c"]);
  });
});
