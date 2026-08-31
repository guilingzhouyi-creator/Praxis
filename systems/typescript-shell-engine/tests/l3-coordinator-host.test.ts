import { describe, expect, it } from "vitest";
import { makeMessage, type Message } from "../src/protocol/wire-envelope.ts";
import { L2SessionAuthority } from "../src/engine/l2-session-authority.ts";
import {
  EventReplayLedger,
  SessionSequenceAllocator,
  createL3CoordinatorHost,
  type AgentIdentity,
  type KernelExecutionRequest,
  type RustKernelExecutionPort,
} from "../src/l3/l3-agent-entry.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
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

describe("TypeScript L3 coordinator host composition", () => {
  it("wires runtime events to replay and L2 output in one deterministic sequence", async () => {
    const messages: Message[] = [];
    const host = createL3CoordinatorHost({
      runtime: {
        decision: {
          async decide() {
            return { decisionId: "decision-1", actions: [], answer: "ok" };
          },
        },
        execution: execution(),
      },
      sessionProjection: {
        sequence: new SessionSequenceAllocator(),
        sink: { publish: (message) => messages.push(message) },
      },
    });
    host.coordinator.registerCell(identity.cellId);

    await host.coordinator.submitIntent(
      makeMessage(identity.sessionId, 1, "intent", { text: "hello" }, "trace-1"),
      identity,
    );

    expect(messages.map((message) => `${message.kind}:${message.seq}`)).toEqual([
      "event:1",
      "event:2",
      "event:3",
      "result:4",
    ]);
    expect(host.replay.resume({ identity, afterEventSeq: 0 }).events.map((event) => event.eventSeq)).toEqual([1, 2, 3]);
    expect(messages[3]?.payload).toMatchObject({ success: true, output: "ok" });
  });

  it("keeps replay and L2 projections isolated from an external observer mutation", async () => {
    const messages: Message[] = [];
    const host = createL3CoordinatorHost({
      runtime: {
        decision: {
          async decide() {
            return {
              decisionId: "decision-1",
              actions: [{ kind: "emit", actionId: "event-1", eventType: "progress", data: { step: 1 } }],
            };
          },
        },
        execution: execution(),
        events: {
          publish(event) {
            event.data.action_id = "observer-mutated";
          },
        },
      },
      sessionProjection: {
        sequence: new SessionSequenceAllocator(),
        sink: { publish: (message) => messages.push(message) },
      },
    });
    host.coordinator.registerCell(identity.cellId);

    await host.coordinator.submitIntent(
      makeMessage(identity.sessionId, 1, "intent", { text: "observe" }, "trace-1"),
      identity,
    );

    const replayEvents = host.replay.resume({ identity, afterEventSeq: 0 }).events;
    expect(replayEvents.find((event) => event.type === "event_emitted")?.data).toMatchObject({
      action_id: "event-1",
      event_type: "progress",
      data: { step: 1 },
    });
    const projectedEvent = messages.find(
      (message) => message.kind === "event" && message.payload.event_type === "event_emitted",
    );
    expect(projectedEvent?.payload.data).toMatchObject({
      details: { action_id: "event-1", event_type: "progress" },
    });
  });

  it("accepts an injected replay ledger without replacing its existing window", async () => {
    const messages: Message[] = [];
    const replay = new EventReplayLedger({
      maxEventsPerIdentity: 4,
    });
    const host = createL3CoordinatorHost({
      replay,
      runtime: {
        decision: {
          async decide() {
            return { decisionId: "decision-1", actions: [], answer: "ok" };
          },
        },
        execution: execution(),
      },
      sessionProjection: {
        sequence: new SessionSequenceAllocator(),
        sink: { publish: (message) => messages.push(message) },
      },
    });
    host.coordinator.registerCell(identity.cellId);
    await host.coordinator.submitIntent(
      makeMessage(identity.sessionId, 1, "intent", { text: "reuse ledger" }, "trace-1"),
      identity,
    );

    expect(host.replay).toBe(replay);
    expect(replay.snapshot(identity)).toMatchObject({ retainedEvents: 3, nextEventSeq: 4 });
    expect(messages).toHaveLength(4);
  });

  it("can bind the host directly to the L2 authoritative outbox and cursors", async () => {
    const authority = new L2SessionAuthority({ outboxMaxlen: 8 });
    const host = createL3CoordinatorHost({
      sessionAuthority: authority,
      runtime: {
        decision: {
          async decide() {
            return { decisionId: "decision-1", actions: [], answer: "authoritative" };
          },
        },
        execution: execution(),
      },
    });
    host.coordinator.registerCell(identity.cellId);

    await host.coordinator.submitIntent(
      makeMessage(identity.sessionId, 1, "intent", { text: "authority" }, "trace-1"),
      identity,
    );
    authority.attach(identity.sessionId, "view-1");

    const replay = authority.replay(identity.sessionId, "view-1");
    expect(replay.map((message) => `${message.kind}:${message.seq}`)).toEqual([
      "event:1",
      "event:2",
      "event:3",
      "result:4",
    ]);
    authority.ack(identity.sessionId, "view-1", 2);
    expect(authority.replay(identity.sessionId, "view-1").map((message) => message.seq)).toEqual([3, 4]);
    expect(host.projection).toBeDefined();
  });

  it("requires exactly one L2 projection source", () => {
    expect(() =>
      createL3CoordinatorHost({
        runtime: {
          decision: {
            async decide() {
              return { decisionId: "decision-1", actions: [] };
            },
          },
          execution: execution(),
        },
      }),
    ).toThrow(/exactly one/);
  });
});
