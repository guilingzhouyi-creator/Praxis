import { describe, expect, it } from "vitest";
import { makeMessage } from "../src/protocol/wire-envelope.ts";
import type { JsonObject } from "../src/protocol/wire-records.ts";
import {
  AgentRuntime,
  AgentRuntimeError,
  createBoundedDecisionPort,
  createRustProtocolExecutionPort,
  intentFromL2,
  type AgentDecisionContext,
  type AgentDecisionPort,
  type AgentEventSink,
  type AgentIdentity,
  type AgentInput,
  type KernelExecutionRequest,
  type DecisionProviderRequest,
  type RustExecutionReceipt,
  type RustKernelExecutionPort,
} from "../src/l3/l3-agent-entry.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
};

function input(inputId = "session-1:1"): AgentInput {
  return {
    inputId,
    inputSeq: 1,
    text: "inspect the workspace",
    traceId: "trace-1",
    identity,
  };
}

function makeDecision(): AgentDecisionPort {
  return {
    async decide() {
      return {
        decisionId: "decision-1",
        answer: "submitted",
        actions: [
          {
            kind: "kernel_request",
            actionId: "action-1",
            operation: "terminal.submit",
            args: { bytes: 3 },
            ring: 1,
            danger: 0,
          },
          {
            kind: "emit",
            actionId: "action-2",
            eventType: "agent.note",
            data: { phase: "inspection" },
          },
        ],
      };
    },
  };
}

function makeRustPort(received: KernelExecutionRequest[]): RustKernelExecutionPort {
  return {
    authority: "rust",
    async submit(request) {
      received.push(request);
      return {
        receiptId: `receipt-${request.requestId}`,
        requestId: request.requestId,
        accepted: true,
        status: "completed",
        traceId: request.traceId,
        data: { kernel: "rust" },
      };
    },
  };
}

function makeSink(events: string[]): AgentEventSink {
  return {
    publish(event) {
      events.push(event.type);
    },
  };
}

describe("independent TypeScript L3 agent runtime", () => {
  it("maps an L2 intent without importing or executing a host side effect", () => {
    const message = makeMessage("session-1", 7, "intent", { text: "hello" }, "trace-7", 10);
    const mapped = intentFromL2(message, identity);
    expect(mapped).toMatchObject({
      inputId: "session-1:7",
      inputSeq: 7,
      text: "hello",
      traceId: "trace-7",
    });
    expect(mapped.identity).not.toBe(identity);
  });

  it("coordinates a decision and delegates kernel work only through Rust", async () => {
    const requests: KernelExecutionRequest[] = [];
    const events: string[] = [];
    const runtime = new AgentRuntime({
      decision: makeDecision(),
      execution: makeRustPort(requests),
      events: makeSink(events),
      clock: () => 10,
    });

    const result = await runtime.run(input());

    expect(result.state).toBe("completed");
    expect(result.answer).toBe("submitted");
    expect(result.receipts).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      authority: "rust",
      operation: "terminal.submit",
      ring: 1,
      danger: 0,
      traceId: "trace-1",
    });
    expect(events).toEqual([
      "run_started",
      "decision_ready",
      "kernel_request_submitted",
      "kernel_request_completed",
      "event_emitted",
      "run_completed",
    ]);
    expect(runtime.snapshot(identity)).toMatchObject({
      state: "completed",
      activeInputId: null,
      acceptedInputs: 1,
    });
  });

  it("detaches caller input before invoking provider code", async () => {
    const requests: KernelExecutionRequest[] = [];
    const original = input("session-1:5");
    const runtime = new AgentRuntime({
      decision: {
        async decide(providerInput) {
          const mutable = providerInput as unknown as {
            text: string;
            identity: AgentIdentity;
          };
          mutable.text = "provider mutation";
          mutable.identity = {
            agentId: "spoofed-agent",
            cellId: "spoofed-cell",
            sessionId: "spoofed-session",
            terminalId: "spoofed-terminal",
          };
          return {
            decisionId: "detached-input",
            actions: [{
              kind: "kernel_request",
              actionId: "action-detached",
              operation: "terminal.submit",
              args: {},
              ring: 1,
              danger: 0,
            }],
          };
        },
      },
      execution: makeRustPort(requests),
    });

    const result = await runtime.run(original);

    expect(original.text).toBe("inspect the workspace");
    expect(original.identity).toEqual(identity);
    expect(result.identity).toEqual(identity);
    expect(requests[0].identity).toEqual(identity);
  });

  it("projects bounded event data without retaining provider-owned aliases", async () => {
    const data = { phase: "inspection", nested: { count: 1 } };
    const seen: Record<string, unknown>[] = [];
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return {
            decisionId: "decision-data",
            actions: [{ kind: "emit", actionId: "event-1", eventType: "agent.note", data }],
          };
        },
      },
      execution: makeRustPort([]),
      events: {
        publish(event) {
          if (event.type === "event_emitted") seen.push(event.data);
        },
      },
    });

    await runtime.run(input("session-1:3"));
    data.nested.count = 9;
    expect(seen[0]).toEqual({
      action_id: "event-1",
      event_type: "agent.note",
      data: { phase: "inspection", nested: { count: 1 } },
    });
  });

  it("fails closed when Rust rejects a capability request", async () => {
    const denied: RustKernelExecutionPort = {
      authority: "rust",
      async submit(request) {
        const receipt: RustExecutionReceipt = {
          receiptId: "receipt-denied",
          requestId: request.requestId,
          accepted: false,
          status: "rejected",
          traceId: request.traceId,
          error: "capability denied",
        };
        return receipt;
      },
    };
    const runtime = new AgentRuntime({
      decision: makeDecision(),
      execution: denied,
    });

    await expect(runtime.run(input())).rejects.toMatchObject({
      code: "execution_rejected",
    });
    expect(runtime.snapshot(identity)).toMatchObject({
      state: "failed",
      activeInputId: null,
      lastError: { code: "execution_rejected" },
    });
  });

  it("bounds action count before any Rust request is submitted", async () => {
    const received: KernelExecutionRequest[] = [];
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return {
            decisionId: "too-large",
            actions: Array.from({ length: 3 }, (_, index) => ({
              kind: "kernel_request" as const,
              actionId: `action-${index}`,
              operation: "terminal.submit",
              args: {},
              ring: 1,
              danger: 0,
            })),
          };
        },
      },
      execution: makeRustPort(received),
      limits: { maxActionsPerInput: 2 },
    });

    await expect(runtime.run(input("session-1:2"))).rejects.toMatchObject({
      code: "action_limit",
    });
    expect(received).toHaveLength(0);
  });

  it("fails closed for cyclic action data before any event is emitted", async () => {
    const data = {} as JsonObject;
    data.self = data;
    const events: string[] = [];
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return {
            decisionId: "cyclic",
            actions: [{ kind: "emit", actionId: "event-cyclic", eventType: "agent.note", data }],
          };
        },
      },
      execution: makeRustPort([]),
      events: makeSink(events),
    });

    await expect(runtime.run(input("session-1:4"))).rejects.toMatchObject({
      code: "invalid_decision",
    });
    expect(events).toEqual(["run_started", "run_failed"]);
  });
});

describe("Rust protocol execution port", () => {
  it("carries gate inputs and maps a result envelope to a receipt", async () => {
    const calls: Array<{
      name: string;
      payload: Record<string, unknown>;
      sessionId?: string;
      traceId?: string;
    }> = [];
    const port = createRustProtocolExecutionPort({
      sessionId: identity.sessionId,
      async commandPayload(name, payload = {}, sessionId, traceId) {
        calls.push({ name, payload, sessionId, traceId });
        return [
          makeMessage(
            identity.sessionId,
            11,
            "result",
            { success: true, output: "ok", receipt_id: "receipt-1", request_id: "action-1" },
            "trace-1",
            10,
          ),
          makeMessage(identity.sessionId, 12, "ack", { ack_seq: 1 }, "trace-1", 10),
        ];
      },
    });

    const receipt = await port.submit({
      requestId: "action-1",
      authority: "rust",
      operation: "terminal.submit",
      args: { bytes: 3 },
      ring: 1,
      danger: 0,
      identity,
      traceId: "trace-1",
    });

    expect(calls).toEqual([{
      name: "terminal.submit",
      payload: {
        args: ['{"bytes":3}'],
        danger: 0,
        request_id: "action-1",
        ring: 1,
      },
      sessionId: "session-1",
      traceId: "trace-1",
    }]);
    expect(receipt).toMatchObject({
      receiptId: "receipt-1",
      requestId: "action-1",
      accepted: true,
      status: "completed",
      traceId: "trace-1",
      data: { output: "ok" },
    });
  });

  it("fails closed when Rust echoes a different request id", async () => {
    const port = createRustProtocolExecutionPort({
      sessionId: identity.sessionId,
      commandPayload: async () => [
        makeMessage(
          identity.sessionId,
          11,
          "result",
          { success: true, request_id: "other-action" },
          "trace-1",
          10,
        ),
      ],
    });

    await expect(port.submit({
      requestId: "action-1",
      authority: "rust",
      operation: "status",
      args: {},
      ring: 1,
      danger: 0,
      identity,
      traceId: "trace-1",
    })).rejects.toMatchObject({ code: "invalid_receipt" });
  });

  it("rejects a bridge bound to a different session", async () => {
    const port = createRustProtocolExecutionPort({
      sessionId: "other-session",
      commandPayload: async () => [],
    });
    await expect(port.submit({
      requestId: "action-1",
      authority: "rust",
      operation: "status",
      args: {},
      ring: 1,
      danger: 0,
      identity,
      traceId: "trace-1",
    })).rejects.toMatchObject({ code: "execution_failed" });
  });
});

describe("bounded TypeScript L3 decision provider", () => {
  it("passes detached context with deadline and bounded work metadata", async () => {
    const observed: DecisionProviderRequest[] = [];
    const original = input("session-1:9");
    const context: AgentDecisionContext = {
      identity,
      input: original,
      history: [],
    };
    const port = createBoundedDecisionPort({
      async decide(request) {
        observed.push(request);
        (request.input as { text: string }).text = "provider-local";
        (request.context.identity as { sessionId: string }).sessionId = "provider-local";
        return { decisionId: "provider-decision", actions: [] };
      },
    }, {
      maxLatencyMs: 50,
      clock: () => 100,
    });

    const decision = await port.decide(original, context);

    expect(decision.decisionId).toBe("provider-decision");
    expect(observed[0]).toMatchObject({
      deadlineAt: 100.05,
      budget: {
        maxLatencyMs: 50,
        inputBytes: new TextEncoder().encode(original.text).byteLength,
        historyEntries: 0,
      },
    });
    expect(original.text).toBe("inspect the workspace");
    expect(original.identity).toEqual(identity);
    expect(context.identity).toEqual(identity);
  });

  it("fails closed at the provider deadline and emits bounded telemetry", async () => {
    const telemetry: Array<{ outcome: string; elapsedMs: number }> = [];
    const port = createBoundedDecisionPort({
      async decide() {
        return new Promise(() => undefined);
      },
    }, {
      maxLatencyMs: 5,
      onTelemetry(event) {
        telemetry.push({ outcome: event.outcome, elapsedMs: event.elapsedMs });
      },
    });

    await expect(port.decide(input("session-1:10"), {
      identity,
      input: input("session-1:10"),
      history: [],
    })).rejects.toMatchObject({ code: "decision_timeout" });
    expect(telemetry).toHaveLength(1);
    expect(telemetry[0]?.outcome).toBe("timeout");
    expect(telemetry[0]?.elapsedMs).toBeGreaterThanOrEqual(0);
  });

  it("propagates caller cancellation to the provider signal", async () => {
    const controller = new AbortController();
    let providerAborted = false;
    const port = createBoundedDecisionPort({
      async decide(request) {
        return new Promise((resolve) => {
          request.context.signal?.addEventListener("abort", () => {
            providerAborted = true;
            resolve({ decisionId: "cancelled", actions: [] });
          }, { once: true });
        });
      },
    }, { maxLatencyMs: 500 });

    const pending = port.decide(input("session-1:11"), {
      identity,
      input: input("session-1:11"),
      history: [],
      signal: controller.signal,
    });
    controller.abort();

    await expect(pending).rejects.toMatchObject({ code: "cancelled" });
    expect(providerAborted).toBe(true);
  });
});
