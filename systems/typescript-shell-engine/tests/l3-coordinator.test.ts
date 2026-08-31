import { describe, expect, it } from "vitest";
import { makeMessage } from "../src/protocol/wire-envelope.ts";
import {
  AgentRuntime,
  L3Coordinator,
  AgentRuntimeError,
  L2SessionProjection,
  SessionSequenceAllocator,
  type AgentDecisionPort,
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

function runtime(decision: AgentDecisionPort = {
  async decide() {
    return { decisionId: "decision", actions: [], answer: "ok" };
  },
}): AgentRuntime {
  return new AgentRuntime({ decision, execution: execution() });
}

function input(identity: AgentIdentity = target, inputSeq = 1, traceId = "trace-1"): AgentInput {
  return {
    inputId: `${identity.sessionId}:${inputSeq}`,
    inputSeq,
    text: `input-${inputSeq}`,
    traceId,
    identity,
  };
}

describe("TypeScript L3 coordinator facade", () => {
  it("normalizes an L2 intent, admits it to the registered Cell, and exposes detached snapshots", async () => {
    const observed: string[] = [];
    const coordinator = new L3Coordinator({
      runtime: runtime({
        async decide(currentInput) {
          observed.push(`${currentInput.identity.cellId}:${currentInput.text}`);
          return { decisionId: "decision-1", actions: [], answer: "accepted" };
        },
      }),
    });
    expect(coordinator.registerCell("cell-a")).toEqual({ cellId: "cell-a", loopCount: 0 });

    const message = makeMessage("session-source", 1, "intent", { text: "hello coordinator" }, "trace-1");
    const result = await coordinator.submitIntent(message, source);

    expect(result).toMatchObject({
      runId: "session-source:1",
      identity: source,
      answer: "accepted",
    });
    expect(observed).toEqual(["cell-a:hello coordinator"]);
    expect(coordinator.snapshot(source)).toMatchObject({
      identity: source,
      loop: {
        state: "accepting",
        activeInputId: null,
        submittedInputs: 1,
        completedInputs: 1,
      },
      agent: {
        state: "completed",
        acceptedInputs: 1,
      },
    });

    const snapshots = coordinator.snapshots();
    expect(snapshots).toHaveLength(1);
    const detached = snapshots[0]!;
    (detached.identity as { agentId: string }).agentId = "caller-mutated";
    expect(coordinator.snapshot(source)?.identity.agentId).toBe("agent-source");
  });

  it("keeps Cell registration authoritative for local input and rejects non-intents", async () => {
    const coordinator = new L3Coordinator({ runtime: runtime() });
    await expect(coordinator.submit(input(source))).rejects.toMatchObject({
      code: "route_cell_not_found",
    });
    expect(coordinator.registrations()).toEqual([]);

    coordinator.registerCell("cell-a");
    const command = makeMessage("session-source", 1, "command", { name: "status" }, "trace-1");
    await expect(coordinator.submitIntent(command, source)).rejects.toMatchObject({
      code: "invalid_input",
    });
  });

  it("routes across Cells and records bounded payload-free route evidence", async () => {
    let now = 0;
    const coordinator = new L3Coordinator({
      runtime: runtime(),
      maxRouteLatencySamples: 2,
      clock: () => now++,
    });
    coordinator.registerCell("cell-a");
    coordinator.registerCell("cell-b");

    const receipt = await coordinator.route({
      routeId: "route-1",
      traceId: "trace-1",
      source,
      target,
      input: input(target),
      metadata: { purpose: "coordinator-test" },
    });
    expect(receipt).toMatchObject({
      status: "delivered",
      routeId: "route-1",
      target,
      hops: 1,
    });

    await expect(coordinator.route({
      routeId: "invalid",
      traceId: "trace-1",
      source,
      target: { ...target, cellId: source.cellId },
      input: input({ ...target, cellId: source.cellId }),
    })).rejects.toMatchObject({ code: "route_same_cell" });

    const stats = coordinator.routeStats();
    expect(stats).toMatchObject({
      attempted: 2,
      delivered: 1,
      rejected: 1,
      validationErrors: 1,
      active: 0,
      latencySampleCount: 2,
      latencySamplesDropped: 0,
      p50LatencyMs: 1,
      p95LatencyMs: 1,
      p99LatencyMs: 1,
    });
  });

  it("turns target runtime failures into rejected receipts and preserves drain semantics", async () => {
    const coordinator = new L3Coordinator({
      runtime: new AgentRuntime({
        decision: {
          async decide() {
            throw new AgentRuntimeError("decision_failed", "decision unavailable");
          },
        },
        execution: execution(),
      }),
    });
    coordinator.registerCell("cell-a");
    coordinator.registerCell("cell-b");

    const receipt = await coordinator.route({
      routeId: "route-rejected",
      traceId: "trace-1",
      source,
      target,
      input: input(target),
    });
    expect(receipt).toMatchObject({
      status: "rejected",
      error: { code: "decision_failed" },
    });
    expect(coordinator.routeStats()).toMatchObject({
      attempted: 1,
      delivered: 0,
      rejected: 1,
      validationErrors: 0,
      active: 0,
    });

    await coordinator.drain();
    expect(coordinator.registrations()).toEqual([
      { cellId: "cell-a", loopCount: 0 },
      { cellId: "cell-b", loopCount: 1 },
    ]);
  });

  it("keeps repeated Cell registration idempotent", async () => {
    const coordinator = new L3Coordinator({ runtime: runtime() });
    expect(coordinator.registerCell("cell-a", { maxPendingInputs: 2 })).toEqual({ cellId: "cell-a", loopCount: 0 });
    expect(coordinator.registerCell("cell-a")).toEqual({ cellId: "cell-a", loopCount: 0 });
    await expect(coordinator.submit(input(source))).resolves.toMatchObject({ identity: source });
    expect(coordinator.unregisterCell("cell-a")).toBe(true);
    expect(coordinator.snapshot(source)).toBeNull();
  });

  it("projects coordinator intent outcomes back to the L2 session sink", async () => {
    const messages: Array<{ kind: string; seq: number; success?: boolean }> = [];
    const projection = new L2SessionProjection({
      sequence: new SessionSequenceAllocator(),
      sink: {
        publish(message) {
          messages.push({
            kind: message.kind,
            seq: message.seq,
            success: typeof message.payload.success === "boolean" ? message.payload.success : undefined,
          });
        },
      },
    });
    const coordinator = new L3Coordinator({
      runtime: runtime(),
      sessionProjection: projection,
    });
    coordinator.registerCell("cell-a");

    const message = makeMessage("session-source", 1, "intent", { text: "project result" }, "trace-1");
    await coordinator.submitIntent(message, source);

    expect(messages).toEqual([{ kind: "result", seq: 1, success: true }]);
  });

  it("projects failed intent admission without changing the runtime error", async () => {
    const messages: Array<{ kind: string; seq: number; success?: boolean }> = [];
    const projection = new L2SessionProjection({
      sequence: new SessionSequenceAllocator(),
      sink: {
        publish(message) {
          messages.push({
            kind: message.kind,
            seq: message.seq,
            success: typeof message.payload.success === "boolean" ? message.payload.success : undefined,
          });
        },
      },
    });
    const coordinator = new L3Coordinator({
      runtime: new AgentRuntime({
        decision: {
          async decide() {
            throw new AgentRuntimeError("decision_failed", "decision unavailable");
          },
        },
        execution: execution(),
      }),
      sessionProjection: projection,
    });
    coordinator.registerCell("cell-a");

    const message = makeMessage("session-source", 1, "intent", { text: "project failure" }, "trace-1");
    await expect(coordinator.submitIntent(message, source)).rejects.toMatchObject({
      code: "decision_failed",
    });
    expect(messages).toEqual([{ kind: "result", seq: 1, success: false }]);
  });
});
