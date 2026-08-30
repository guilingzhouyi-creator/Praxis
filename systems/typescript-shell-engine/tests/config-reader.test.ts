import { describe, it, expect, vi } from "vitest";
import { ConfigReader } from "../src/engine/config-reader.ts";
import type { ProtocolBridge } from "../src/engine/bridge.ts";

function fakeBridge(settingsGet: (key: string) => Promise<never[] | any[]>): ProtocolBridge {
  return { settingsGet } as unknown as ProtocolBridge;
}

describe("ConfigReader", () => {
  it("returns fallback on missing payload and does not cache it", async () => {
    const bridge = fakeBridge(async () => []);
    const reader = new ConfigReader(bridge, { ttlMs: 10_000 });
    expect(await reader.getString("missing", "fb")).toBe("fb");
    // second call still hits bridge (not cached) — swap to real value
    const bridge2 = fakeBridge(async () => [{ payload: { missing: "real" } }]);
    (reader as any).bridge = bridge2;
    expect(await reader.getString("missing", "fb")).toBe("real");
  });

  it("parses direct key payload", async () => {
    const bridge = fakeBridge(async (k: string) => [{ payload: { [k]: "v1" } }]);
    const reader = new ConfigReader(bridge);
    expect(await reader.getString("k1")).toBe("v1");
  });

  it("parses value fallback shape", async () => {
    const bridge = fakeBridge(async () => [{ payload: { value: "from-value" } }]);
    const reader = new ConfigReader(bridge);
    expect(await reader.getString("any")).toBe("from-value");
  });

  it("reads a Rust settings command reply through its versioned values map", async () => {
    const bridge = fakeBridge(async () => [{
      payload: {
        success: true,
        operation: "settings_get",
        revision: 2,
        source: "fallback",
        key: "theme",
        value: "dark",
        values: { theme: "dark" },
      },
    }]);
    const reader = new ConfigReader(bridge);
    expect(await reader.getString("theme")).toBe("dark");
  });

  it("uses TTL cache", async () => {
    let calls = 0;
    const bridge = fakeBridge(async (k: string) => {
      calls++;
      return [{ payload: { [k]: "cached" } }];
    });
    const reader = new ConfigReader(bridge, { ttlMs: 50 });
    expect(await reader.getString("k")).toBe("cached");
    expect(calls).toBe(1);
    // within TTL hits cache
    expect(await reader.getString("k")).toBe("cached");
    expect(calls).toBe(1);
    // after TTL expiry refetches
    await new Promise((r) => setTimeout(r, 60));
    expect(await reader.getString("k")).toBe("cached");
    expect(calls).toBe(2);
  });

  it("invalidate clears cache", async () => {
    const bridge = fakeBridge(async (k: string) => [{ payload: { [k]: "v" } }]);
    const reader = new ConfigReader(bridge);
    await reader.getString("a");
    expect((reader as any).cache.size).toBe(1);
    reader.invalidate();
    expect((reader as any).cache.size).toBe(0);
  });

  it("returns fallback on empty key", async () => {
    const bridge = fakeBridge(async () => [{ payload: { "": "x" } }]);
    const reader = new ConfigReader(bridge);
    expect(await reader.getString("", "fb")).toBe("fb");
  });
});
