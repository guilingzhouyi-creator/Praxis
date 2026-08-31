import { describe, expect, it } from "vitest";
import {
  AgentCell,
  AgentLoop,
  AgentRuntime,
  AgentRuntimeError,
  type AgentDecisionPort,
  type AgentIdentity,
  type AgentInput,
  type KernelExecutionRequest,
  type RustKernelExecutionPort,
} from "../src/l3/l3-agent-entry.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
};

function input(inputSeq: number, currentIdentity: AgentIdentity = identity): AgentInput {
  return {
    inputId: `${currentIdentity.sessionId}:${inputSeq}`,
    inputSeq,
    text: `input-${inputSeq}`,
    traceId: `trace-${inputSeq}`,
    identity: currentIdentity,
  };
}

function executionPort(): RustKernelExecutionPort {
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

function emptyDecision(): AgentDecisionPort {
  return {
    async decide() {
      return { decisionId: "decision", actions: [], answer: "ok" };
    },
  };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

async function waitFor(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("condition was not observed before timeout");
}

describe("TypeScript L3 AgentLoop", () => {
  it("serializes one identity FIFO while returning each result to its caller", async () => {
    const observed: number[] = [];
    const runtime = new AgentRuntime({
      decision: {
        async decide(currentInput) {
          observed.push(currentInput.inputSeq);
          await Promise.resolve();
          return { decisionId: `decision-${currentInput.inputSeq}`, actions: [] };
        },
      },
      execution: executionPort(),
    });
    const loop = new AgentLoop(identity, { runtime, maxPendingInputs: 3 });

    const results = await Promise.all([
      loop.submit(input(1)),
      loop.submit(input(2)),
      loop.submit(input(3)),
    ]);

    expect(observed).toEqual([1, 2, 3]);
    expect(results.map((result) => result.runId)).toEqual(["session-1:1", "session-1:2", "session-1:3"]);
    expect(loop.snapshot()).toMatchObject({
      state: "accepting",
      activeInputId: null,
      queueDepth: 0,
      submittedInputs: 3,
      completedInputs: 3,
      failedInputs: 0,
      lastInputSeq: 3,
    });
  });

  it("applies backpressure only to pending work and preserves the active turn", async () => {
    const gate = deferred<void>();
    const started: number[] = [];
    const runtime = new AgentRuntime({
      decision: {
        async decide(currentInput) {
          started.push(currentInput.inputSeq);
          if (currentInput.inputSeq === 1) await gate.promise;
          return { decisionId: `decision-${currentInput.inputSeq}`, actions: [] };
        },
      },
      execution: executionPort(),
    });
    const loop = new AgentLoop(identity, { runtime, maxPendingInputs: 1 });

    const first = loop.submit(input(1));
    await Promise.resolve();
    const second = loop.submit(input(2));
    await expect(loop.submit(input(3))).rejects.toMatchObject({ code: "loop_queue_full" });
    expect(loop.snapshot()).toMatchObject({
      activeInputId: "session-1:1",
      queueDepth: 1,
      submittedInputs: 2,
    });

    gate.resolve();
    await expect(first).resolves.toMatchObject({ runId: "session-1:1" });
    await expect(second).resolves.toMatchObject({ runId: "session-1:2" });
    expect(started).toEqual([1, 2]);
  });

  it("stops active and queued work without affecting a sibling Cell identity", async () => {
    const gate = deferred<void>();
    const otherIdentity = { ...identity, terminalId: "terminal-2" };
    const runtime = new AgentRuntime({
      decision: {
        async decide(currentInput, context) {
          if (currentInput.identity.terminalId === identity.terminalId) {
            return new Promise((resolve, reject) => {
              context.signal?.addEventListener("abort", () => reject(new AgentRuntimeError("cancelled", "stopped")), {
                once: true,
              });
              void gate.promise.then(() => resolve({ decisionId: "released", actions: [] }));
            });
          }
          return { decisionId: "sibling", actions: [] };
        },
      },
      execution: executionPort(),
    });
    const cell = new AgentCell({ runtime, maxPendingInputs: 1 });
    const active = cell.submit(input(1));
    const activeOutcome = active.then(
      (value) => ({ value }),
      (error) => ({ error }),
    );
    await waitFor(() => cell.snapshot(identity)?.activeInputId === "session-1:1");
    const queued = cell.submit(input(2));
    const queuedOutcome = queued.then(
      (value) => ({ value }),
      (error) => ({ error }),
    );
    const sibling = cell.submit(input(1, otherIdentity));

    cell.stop(identity);
    expect(await activeOutcome).toMatchObject({ error: { code: "cancelled" } });
    expect(await queuedOutcome).toMatchObject({ error: { code: "loop_stopped" } });
    await expect(sibling).resolves.toMatchObject({ runId: "session-1:1" });
    expect(cell.snapshot(identity)).toMatchObject({ state: "stopped", failedInputs: 2 });
    expect(cell.snapshot(otherIdentity)).toMatchObject({ state: "accepting", completedInputs: 1 });
    gate.resolve();
  });

  it("isolates full identity tuples and rejects sequence reuse", async () => {
    const runtime = new AgentRuntime({
      decision: emptyDecision(),
      execution: executionPort(),
    });
    const cell = new AgentCell({ runtime });
    const first = await cell.submit(input(1));
    expect(first.state).toBe("completed");
    await expect(cell.submit(input(1))).rejects.toMatchObject({ code: "invalid_input" });

    const otherSession = { ...identity, sessionId: "session-2" };
    await expect(cell.submit(input(1, otherSession))).resolves.toMatchObject({
      identity: otherSession,
    });
    expect(cell.snapshots().map((snapshot) => snapshot.identity.sessionId)).toEqual(["session-1", "session-2"]);
  });

  it("drains admitted inputs and then closes admission", async () => {
    const runtime = new AgentRuntime({
      decision: emptyDecision(),
      execution: executionPort(),
    });
    const cell = new AgentCell({ runtime });
    const pending = cell.submit(input(1));
    await cell.drain();
    await expect(pending).resolves.toMatchObject({ state: "completed" });
    expect(cell.snapshot(identity)).toMatchObject({ state: "stopped" });
    await expect(cell.submit(input(2))).rejects.toMatchObject({ code: "loop_stopped" });
  });
});
