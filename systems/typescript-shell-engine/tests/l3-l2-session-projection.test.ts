import { describe, expect, it } from "vitest";
import { validateMessage } from "../src/protocol/wire-envelope.ts";
import {
  AgentRuntime,
  AgentRuntimeError,
  EventReplayLedger,
  L2SessionProjection,
  SessionSequenceAllocator,
  fanoutAgentEventSinks,
  type AgentIdentity,
  type AgentInput,
  type AgentRuntimeEvent,
  type AgentRunResult,
} from "../src/l3/l3-agent-entry.ts";
import type { AgentEventSink } from "../src/l3/contracts/agent-contracts.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
};

const input: AgentInput = {
  inputId: "session-1:1",
  inputSeq: 1,
  text: "project this",
  traceId: "trace-1",
  identity,
};

const result: AgentRunResult = {
  contractVersion: 1,
  runId: input.inputId,
  identity,
  state: "completed",
  answer: "done",
  actions: 2,
  receipts: [],
  toolResults: [],
  cardReceipts: [],
  scheduleReceipts: [],
};

function event(eventSeq = 1): AgentRuntimeEvent {
  return {
    contractVersion: 1,
    eventSeq,
    type: "event_emitted",
    runId: input.inputId,
    traceId: input.traceId,
    identity,
    data: { value: eventSeq },
    ts: eventSeq,
  };
}

describe("TypeScript L3 to L2 session projection", () => {
  it("allocates monotonic per-session output sequences with a bounded registry", () => {
    const allocator = new SessionSequenceAllocator({ maxSessions: 2 });
    expect(allocator.next("session-a")).toBe(1);
    expect(allocator.next("session-a")).toBe(2);
    expect(allocator.next("session-b")).toBe(1);
    expect(() => allocator.next("session-c")).toThrow(/bound exceeded/);
    expect(allocator.size).toBe(2);
    allocator.clear("session-a");
    expect(allocator.next("session-c")).toBe(1);
  });

  it("projects lifecycle events into validated L2 event envelopes without aliases", () => {
    const projection = new L2SessionProjection({
      sequence: new SessionSequenceAllocator(),
      clock: () => 123,
    });
    const original = event();
    const message = projection.eventMessage(original);

    expect(validateMessage(message)).toEqual([]);
    expect(message).toMatchObject({
      v: 1,
      session_id: "session-1",
      seq: 1,
      trace_id: "trace-1",
      kind: "event",
      payload: {
        event_type: "event_emitted",
        data: {
          event_seq: 1,
          run_id: "session-1:1",
          identity: {
            agent_id: "agent-1",
            cell_id: "cell-1",
            session_id: "session-1",
            terminal_id: "terminal-1",
          },
          details: { value: 1 },
        },
      },
    });
    const data = message.payload.data as Record<string, unknown>;
    const details = data.details as Record<string, unknown>;
    details.value = 99;
    expect(original.data.value).toBe(1);
  });

  it("projects bounded success and failure result envelopes", () => {
    const projection = new L2SessionProjection({
      sequence: new SessionSequenceAllocator(),
      clock: () => 321,
    });
    const success = projection.resultMessage(input, result);
    expect(validateMessage(success)).toEqual([]);
    expect(success).toMatchObject({
      session_id: "session-1",
      seq: 1,
      trace_id: "trace-1",
      kind: "result",
      ts: 321,
      payload: {
        success: true,
        output: "done",
        run_id: "session-1:1",
        action_count: 2,
        receipt_count: 0,
      },
    });

    const failure = projection.failureMessage(
      input,
      new AgentRuntimeError("execution_rejected", "Rust denied the request"),
    );
    expect(validateMessage(failure)).toEqual([]);
    expect(failure).toMatchObject({
      session_id: "session-1",
      seq: 2,
      trace_id: "trace-1",
      kind: "result",
      payload: {
        success: false,
        code: "execution_rejected",
        error: "Rust denied the request",
      },
    });
  });

  it("fans out detached lifecycle events to replay and L2 sinks in order", async () => {
    const replay = new EventReplayLedger();
    const messages: unknown[] = [];
    const projection = new L2SessionProjection({
      sequence: new SessionSequenceAllocator(),
      sink: { publish: (message) => messages.push(message) },
    });
    const mutatingSink: AgentEventSink = {
      publish(currentEvent) {
        (currentEvent.data as { value: number }).value = 99;
      },
    };
    const sink = fanoutAgentEventSinks([mutatingSink, replay, projection]);
    await sink.publish(event());

    expect(replay.resume({ identity, afterEventSeq: 0 }).events[0]?.data.value).toBe(1);
    expect(messages).toHaveLength(1);
    expect((messages[0] as { payload: { data: { details: { value: number } } } }).payload.data.details.value).toBe(1);
  });

  it("can be installed directly as the AgentRuntime event sink", async () => {
    const messages: Array<{ kind: string; seq: number }> = [];
    const projection = new L2SessionProjection({
      sequence: new SessionSequenceAllocator(),
      sink: {
        publish(message) {
          messages.push({ kind: message.kind, seq: message.seq });
        },
      },
    });
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return { decisionId: "decision-1", actions: [], answer: "ok" };
        },
      },
      execution: {
        authority: "rust",
        async submit() {
          throw new Error("not used");
        },
      },
      events: projection,
    });
    await runtime.run(input);
    expect(messages).toEqual([
      { kind: "event", seq: 1 },
      { kind: "event", seq: 2 },
      { kind: "event", seq: 3 },
    ]);
  });
});
