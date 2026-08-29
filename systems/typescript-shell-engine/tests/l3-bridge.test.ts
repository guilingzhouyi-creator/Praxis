import { describe, it, expect } from "vitest";
import { createL3Bridge } from "../src/engine/l3-bridge-interface.ts";
import type { ProtocolBridge } from "../src/engine/bridge.ts";

function makeFakeBridge() {
  const calls: string[][] = [];
    const fake = {
      settingsGet: (...args: string[]) => { calls.push(args); return Promise.resolve([]); },
      settingsSet: (key: string, value: unknown) => { calls.push([key]); return Promise.resolve([]); },
      attach: (sessionId: string, viewId?: string) => { calls.push(["attach", sessionId, viewId ?? ""]); return Promise.resolve([]); },
      detach: (sessionId: string, viewId?: string) => { calls.push(["detach", sessionId, viewId ?? ""]); return Promise.resolve([]); },
      ack: (ackSeq: number, viewId?: string) => { calls.push(["ack", String(ackSeq), viewId ?? ""]); return Promise.resolve([]); },
      replay: (sessionId: string, viewId?: string) => { calls.push(["replay", sessionId, viewId ?? ""]); return Promise.resolve([]); },
      resume: (sessionId: string, viewId?: string) => { calls.push(["resume", sessionId, viewId ?? ""]); return Promise.resolve([]); },
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
    await bridge.session.attach("s2");
    await bridge.session.detach("s2", "view-web");
    await bridge.session.ack(7, "view-tui");
    await bridge.session.replay("s2");
    await bridge.session.resume("s3", "view-cli", 4);
    await bridge.memory.digest();
    await bridge.system.status();
    await bridge.model.specs();
    await bridge.selector.cellLiveness();
    expect(calls).toContainEqual(["attach", "s2", ""]);
    expect(calls).toContainEqual(["detach", "s2", "view-web"]);
    expect(calls).toContainEqual(["ack", "7", "view-tui"]);
    expect(calls).toContainEqual(["resume", "s3", "view-cli"]);
  });

  it("does not re-implement AgentLoop / Scheduler / Memory authority", async () => {
    // The interface must only expose pass-through methods — no business logic.
    const { bridge } = makeFakeBridge();
    for (const group of [bridge.settings, bridge.session, bridge.memory, bridge.system, bridge.model, bridge.selector]) {
      for (const fn of Object.values(group)) {
        const src = fn.toString();
        expect(src.length).toBeLessThan(200); // thin wrappers only
      }
    }
  });
});
