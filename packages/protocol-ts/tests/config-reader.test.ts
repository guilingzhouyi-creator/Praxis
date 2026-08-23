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

  it("parses value and output JSON shapes", async () => {
    const bridge = fakeBridge(async () => [{ payload: { value: "from-value" } }]);
    const reader = new ConfigReader(bridge);
    expect(await reader.getString("any")).toBe("from-value");

    const bridge2 = fakeBridge(async () => [{ payload: { output: JSON.stringify({ any: "from-json" }) } }]);
    const reader2 = new ConfigReader(bridge2);
    expect(await reader2.getString("any")).toBe("from-json");
  });

  it("uses TTL cache and dedupes concurrent requests", async () => {
    let calls = 0;
    const bridge = fakeBridge(async (k: string) => {
      calls++;
      await new Promise((r) => setTimeout(r, 5));
      return [{ payload: { [k]: "cached" } }];
    });
    const reader = new ConfigReader(bridge, { ttlMs: 50 });
    const [a, b] = await Promise.all([reader.getString("k"), reader.getString("k")]);
    expect(a).toBe("cached");
    expect(b).toBe("cached");
    expect(calls).toBe(1);
    // within TTL second sequential call hits cache
    expect(await reader.getString("k")).toBe("cached");
    expect(calls).toBe(1);
    // after TTL expiry refetches
    await new Promise((r) => setTimeout(r, 60));
    expect(await reader.getString("k")).toBe("cached");
    expect(calls).toBe(2);
  });

  it("invalidate and invalidateKey", async () => {
    const bridge = fakeBridge(async (k: string) => [{ payload: { [k]: "v" } }]);
    const reader = new ConfigReader(bridge);
    await reader.getString("a");
    await reader.getString("b");
    reader.invalidateKey("a");
    expect((reader as any).cache.has("a")).toBe(false);
    expect((reader as any).cache.has("b")).toBe(true);
    reader.invalidate();
    expect((reader as any).cache.size).toBe(0);
  });

  it("returns fallback on empty key", async () => {
    const bridge = fakeBridge(async () => [{ payload: { "": "x" } }]);
    const reader = new ConfigReader(bridge);
    expect(await reader.getString("", "fb")).toBe("fb");
  });
});
