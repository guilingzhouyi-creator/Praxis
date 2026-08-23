import { describe, it, expect, vi } from "vitest";
import { ConnectionManager } from "../src/engine/connection-manager.ts";
import { ShellFamily } from "../src/engine/session-family.ts";
import { makeMessage, decodeMessage } from "../src/envelope.ts";
import { decodeRecord, encodeRecord } from "../src/records.ts";

/** Transport factory whose behavior is scripted per test. */
function scriptedFactory(script: Array<() => Promise<string[]>>) {
  const calls = { count: 0 };
  const factory = () => {
    const step = script[Math.min(calls.count, script.length - 1)];
    calls.count += 1;
    return async () => step();
  };
  return { factory, calls };
}

const okStatus = () => [JSON.stringify(makeMessage("sess", 1, "event", { ok: true }))];

describe("ConnectionManager lifecycle", () => {
  it("rejects invalid retry configuration up front", () => {
    expect(() => new ConnectionManager({ factory: () => async () => [], sessionId: "s", maxRetries: -1 }))
      .toThrow(/maxRetries/);
    expect(() => new ConnectionManager({ factory: () => async () => [], sessionId: "s", baseDelayMs: Number.NaN }))
      .toThrow(/baseDelayMs/);
  });

  it("bridge getter throws BRIDGE_UNAVAILABLE when disconnected", () => {
    const cm = new ConnectionManager({ factory: () => async () => [], sessionId: "s" });
    expect(() => cm.bridge).toThrow(/not connected/);
  });

  it("connect probes health then exposes a working bridge", async () => {
    const { factory } = scriptedFactory([okStatus]);
    const cm = new ConnectionManager({ factory, sessionId: "sess", baseDelayMs: 1 });
    const bridge = await cm.connect();
    expect(cm.isConnected()).toBe(true);
    expect(cm.getState().status).toBe("connected");
    // The returned bridge performs real round trips.
    await bridge.command("status");
  });

  it("connect is idempotent once connected", async () => {
    const probeSpy = vi.fn(okStatus);
    const { factory, calls } = scriptedFactory([probeSpy as never]);
    const cm = new ConnectionManager({ factory, sessionId: "sess", baseDelayMs: 1 });
    await cm.connect();
    const first = cm.bridge;
    const again = await cm.connect();
    expect(again).toBe(first);
    expect(calls.count).toBe(1); // factory invoked only for the first connect
  });

  it("connect retries transient failures with backoff then succeeds", async () => {
    let attempts = 0;
    const flaky = (): Promise<string[]> => {
      attempts += 1;
      if (attempts < 3) return Promise.reject(new Error("transport down"));
      return Promise.resolve(okStatus());
    };
    const cm = new ConnectionManager({
      factory: () => flaky, sessionId: "s", maxRetries: 3, baseDelayMs: 1,
    });
    await cm.connect();
    expect(cm.isConnected()).toBe(true);
    expect(attempts).toBeGreaterThanOrEqual(3);
  });

  it("connect exhausts retries and lands disconnected", async () => {
    const alwaysDown = (): Promise<string[]> => Promise.reject(new Error("down"));
    const cm = new ConnectionManager({
      factory: () => alwaysDown, sessionId: "s", maxRetries: 1, baseDelayMs: 1,
    });
    await expect(cm.connect()).rejects.toThrow("down");
    expect(cm.getState().status).toBe("disconnected");
    expect(cm.isConnected()).toBe(false);
  });

  it("disconnect releases the bridge and emits transport:close", async () => {
    const { factory } = scriptedFactory([okStatus]);
    const cm = new ConnectionManager({ factory, sessionId: "sess", baseDelayMs: 1 });
    await cm.connect();
    const closed = vi.fn();
    cm.on("transport:close", closed);
    cm.disconnect();
    expect(cm.getState().status).toBe("disconnected");
    expect(() => cm.bridge).toThrow(/not connected/);
    expect(closed).toHaveBeenCalledOnce();
  });
});

describe("ShellFamily config + binding edges", () => {
  const makeFamily = () => {
    const fam = new ShellFamily();
    fam.register({ name: "terminal" });
    fam.register({ name: "chat", classifier: (line) => line.startsWith("/") });
    return fam;
  };

  it("register rejects shells without a name", () => {
    const fam = new ShellFamily();
    expect(() => fam.register({ name: "" })).toThrow(/non-empty name/);
  });

  it("get throws on unknown shell names; register frontends auto-bind", () => {
    const fam = makeFamily();
    expect(() => fam.get("nope")).toThrow(/unknown shell/);
    const fam2 = new ShellFamily();
    fam2.register({ name: "workspace" }, ["vscode"]);
    expect(fam2.resolve("vscode").name).toBe("workspace");
  });

  it("bind rejects unknown shell and resolve falls back to default", () => {
    const fam = makeFamily();
    expect(() => fam.bind("web", "nope")).toThrow(/unknown shell/);
    fam.bind("web", "chat");
    expect(fam.resolve("web").name).toBe("chat");
    expect(fam.resolve("unbound-frontend").name).toBe("terminal"); // first-registered default
  });

  it("unregister drops bindings and re-homes the default", () => {
    const fam = makeFamily();
    fam.bind("web", "chat");
    fam.unregister("terminal");
    expect(fam.list()).toEqual(["chat"]);
    expect(fam.resolve("unbound").name).toBe("chat"); // default moved to survivor
    expect(fam.resolve("web").name).toBe("chat");
  });

  it("default() throws on an empty family", () => {
    const fam = new ShellFamily();
    expect(() => fam.default()).toThrow(/no shell registered/);
  });

  it("loadConfig honors enabled=false and counts loaded shells", () => {
    const fam = makeFamily();
    expect(fam.loadConfig({ enabled: false })).toBe(0);
    const n = fam.loadConfig({
      enabled: true,
      shells: { workspace: {}, broken: "not-an-object" },
      bindings: { web: "workspace", ghost: "missing" },
      default: "workspace",
    });
    expect(n).toBe(1); // non-object spec skipped
    expect(fam.list()).toContain("workspace");
    expect(fam.resolve("web").name).toBe("workspace");
    expect(fam.snapshot().default).toBe("workspace");
  });

  it("revision() bumps on structural mutations", () => {
    const fam = makeFamily();
    const r0 = fam.revision();
    fam.register({ name: "extra" });
    expect(fam.revision()).toBeGreaterThan(r0);
    const r1 = fam.revision();
    fam.bind("web", "extra");
    expect(fam.revision()).toBeGreaterThan(r1);
    expect(fam.snapshot().revision).toBe(fam.revision());
  });

  it("snapshot captures the full resolution state defensively", () => {
    const fam = makeFamily();
    fam.bind("web", "chat");
    const snap = fam.snapshot();
    expect(snap.shells.sort()).toEqual(["chat", "terminal"]);
    expect(snap.bindings).toEqual({ web: "chat" });
    snap.bindings.web = "tampered";
    expect(fam.snapshot().bindings).toEqual({ web: "chat" }); // defensive copy
  });
});

describe("records branch completion (canonical json guards)", () => {
  it("decodeRecord rejects unknown record types and wrong schema versions", () => {
    expect(() => decodeRecord(JSON.stringify({
      record_type: "mystery", schema_version: 1, data: {},
    }))).toThrow(/unknown record_type/);
    expect(() => decodeRecord(JSON.stringify({
      record_type: "session_identity", schema_version: 99,
      data: { session_id: "s", terminal_id: "t", process_id: "p" },
    }))).toThrow(/schema version/);
  });

  it("encodeRecord strips forward-compatible unknown fields", () => {
    const rec = {
      record_type: "session_identity",
      schema_version: 1,
      data: { session_id: "s", terminal_id: "t", process_id: "p", future_field: 1 },
    };
    const decoded = JSON.parse(encodeRecord(rec)) as { data: Record<string, unknown> };
    expect(decoded.data).not.toHaveProperty("future_field");
    expect(decoded.data).toMatchObject({ session_id: "s", terminal_id: "t", process_id: "p" });
  });

  it("envelope decode round-trips through canonical encoding", () => {
    const msg = makeMessage("sess", 42, "command", { name: "status", args: ["a"] });
    const line = JSON.stringify(msg);
    const decoded = decodeMessage(line);
    expect(decoded.error).toBeNull();
    expect((decoded.message as { seq: number }).seq).toBe(42);
  });
});
