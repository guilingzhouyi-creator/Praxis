import { describe, expect, it } from "vitest";
import {
  AgentCell,
  AgentRuntime,
  CrossCellRouter,
  type AgentIdentity,
  type AgentInput,
  type KernelExecutionRequest,
  type RustKernelExecutionPort,
} from "../src/l3/l3-agent-entry.ts";

const source: AgentIdentity = {
  agentId: "agent-source",
  cellId: "cell-a",
  sessionId: "session-source",
  terminalId: "terminal-source",
};

const target: AgentIdentity = {
  agentId: "agent-target",
  cellId: "cell-b",
  sessionId: "session-target",
  terminalId: "terminal-target",
};

function execution(): RustKernelExecutionPort {
  return {
    authority: "rust",
    async submit(request: KernelExecutionRequest) {
      return {
        receiptId: `receipt-${request.requestId}`,
        requestId: request.requestId,
        accepted: true,
        status: "completed" as const,
        traceId: request.traceId,
      };
    },
  };
}

function input(identity: AgentIdentity = target, traceId = "trace-1"): AgentInput {
  return {
    inputId: `${identity.sessionId}:1`,
    inputSeq: 1,
    text: "cross-cell input",
    traceId,
    identity,
  };
}

function cell(observed: string[]): AgentCell {
  return new AgentCell({
    runtime: new AgentRuntime({
      decision: {
        async decide(currentInput) {
          observed.push(`${currentInput.identity.cellId}:${currentInput.text}`);
          return { decisionId: "decision-1", actions: [], answer: "delivered" };
        },
      },
      execution: execution(),
    }),
  });
}

describe("TypeScript L3B cross-Cell router", () => {
  it("registers bounded Cells and forwards a detached target input", async () => {
    const observed: string[] = [];
    const router = new CrossCellRouter({ maxCells: 2 });
    const sourceCell = cell([]);
    const targetCell = cell(observed);
    expect(router.register("cell-a", sourceCell)).toEqual({ cellId: "cell-a", loopCount: 0 });
    expect(router.register("cell-b", targetCell)).toEqual({ cellId: "cell-b", loopCount: 0 });
    expect(router.register("cell-b", targetCell)).toEqual({ cellId: "cell-b", loopCount: 0 });
    expect(router.registrations()).toEqual([
      { cellId: "cell-a", loopCount: 0 },
      { cellId: "cell-b", loopCount: 0 },
    ]);
    const receipt = await router.route({
      routeId: "route-1",
      traceId: "trace-1",
      source,
      target,
      input: input(),
    });
    expect(receipt.status).toBe("delivered");
    expect(observed).toEqual(["cell-b:cross-cell input"]);
  });

  it("routes across distinct Cells and preserves identity/metadata boundaries", async () => {
    const observed: string[] = [];
    const router = new CrossCellRouter({ maxCells: 2 });
    router.register("cell-a", cell([]));
    const targetCell = cell(observed);
    router.register("cell-b", targetCell);

    const request = {
      routeId: "route-1",
      traceId: "trace-1",
      source,
      target,
      input: input(),
      metadata: { purpose: "handoff", vector: ["l3b", 1, { bounded: true }] },
    };
    const receipt = await router.route(request);

    expect(receipt).toMatchObject({
      contractVersion: 1,
      routeId: "route-1",
      traceId: "trace-1",
      source,
      target,
      hops: 1,
      status: "delivered",
      result: { identity: target, answer: "delivered" },
      metadata: { purpose: "handoff", vector: ["l3b", 1, { bounded: true }] },
    });
    expect(observed).toEqual(["cell-b:cross-cell input"]);
    expect(router.registrations().map((item) => item.cellId)).toEqual(["cell-a", "cell-b"]);
  });

  it("fails closed for same-cell, unknown-cell, identity, trace, and hop violations", async () => {
    const router = new CrossCellRouter({ maxHops: 2 });
    router.register("cell-a", cell([]));
    router.register("cell-b", cell([]));

    await expect(router.route({
      routeId: "same",
      traceId: "trace-1",
      source,
      target: { ...target, cellId: source.cellId },
      input: input({ ...target, cellId: source.cellId }),
    })).rejects.toMatchObject({ code: "route_same_cell" });

    await expect(router.route({
      routeId: "missing",
      traceId: "trace-1",
      source,
      target: { ...target, cellId: "cell-c" },
      input: input({ ...target, cellId: "cell-c" }),
    })).rejects.toMatchObject({ code: "route_cell_not_found" });

    await expect(router.route({
      routeId: "spoof",
      traceId: "trace-1",
      source,
      target,
      input: input({ ...target, terminalId: "spoofed" }),
    })).rejects.toMatchObject({ code: "route_invalid" });

    await expect(router.route({
      routeId: "trace",
      traceId: "trace-1",
      source,
      target,
      input: input(target, "other-trace"),
    })).rejects.toMatchObject({ code: "route_invalid" });

    await expect(router.route({
      routeId: "hop",
      traceId: "trace-1",
      source,
      target,
      input: input(),
      hops: 2,
    })).rejects.toMatchObject({ code: "route_hop_limit" });
  });

  it("returns a rejected receipt for target queue failure without throwing", async () => {
    const router = new CrossCellRouter();
    router.register("cell-a", cell([]));
    const targetCell = new AgentCell({
      runtime: new AgentRuntime({
        decision: {
          async decide() {
            throw new Error("target decision unavailable");
          },
        },
        execution: execution(),
      }),
    });
    router.register("cell-b", targetCell);

    const receipt = await router.route({
      routeId: "rejected",
      traceId: "trace-1",
      source,
      target,
      input: input(),
    });
    expect(receipt).toMatchObject({
      status: "rejected",
      error: { code: "decision_failed" },
    });
  });

  it("enforces registration bounds and keeps unregister side-effect free", async () => {
    const router = new CrossCellRouter({ maxCells: 1 });
    const first = cell([]);
    router.register("cell-a", first);
    expect(() => router.register("cell-b", cell([]))).toThrow(/registered Cell bound/);
    expect(router.unregister("cell-b")).toBe(false);
    expect(router.unregister("cell-a")).toBe(true);
    expect(router.registrations()).toEqual([]);
    await router.drain();
  });
});
