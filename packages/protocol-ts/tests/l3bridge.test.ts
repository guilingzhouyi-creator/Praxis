import { describe, it, expect } from "vitest";
import { createL3Bridge } from "../src/engine/l3-bridge-interface.ts";
import type { ProtocolBridge } from "../src/engine/bridge.ts";

function makeFakeBridge() {
  const calls: string[][] = [];
    const fake = {
      settingsGet: (...args: string[]) => { calls.push(args); return Promise.resolve([]); },
      settingsSet: (key: string, value: unknown) => { calls.push([key]); return Promise.resolve([]); },
      memoryDigest: () => { calls.push(["memory_digest"]); return Promise.resolve([]); },
      systemStatus: () => { calls.push(["status"]); return Promise.resolve([]); },
      modelSpecs: () => { calls.push(["model_specs"]); return Promise.resolve([]); },
      cellLiveness: () => { calls.push(["cell_liveness"]); return Promise.resolve([]); },
    } as unknown as ProtocolBridge;
  return { bridge: createL3Bridge(fake), calls };
}

describe("IL3Bridge interface (TS-mirrorable L3 command surface)", () => {
  it("routes domain-grouped commands to the underlying bridge", async () => {
    const { bridge, calls } = makeFakeBridge();
    await bridge.settings.get("key");
    await bridge.settings.set("k", "v");
    await bridge.memory.digest();
    await bridge.system.status();
    await bridge.model.specs();
    await bridge.selector.cellLiveness();
    expect(calls.length).toBeGreaterThanOrEqual(4);
  });

  it("does not re-implement AgentLoop / Scheduler / Memory authority", async () => {
    // The interface must only expose pass-through methods — no business logic.
    const { bridge } = makeFakeBridge();
    for (const group of [bridge.settings, bridge.memory, bridge.system, bridge.model, bridge.selector]) {
      for (const fn of Object.values(group)) {
        const src = fn.toString();
        expect(src.length).toBeLessThan(200); // thin wrappers only
      }
    }
  });
});
