import { describe, expect, it } from "vitest";
import {
  AgentRuntime,
  EventReplayLedger,
  L3APeerRouter,
  L3ASessionResumeCoordinator,
  type AgentIdentity,
  type AgentRuntimeEvent,
  type KernelExecutionRequest,
  type RustExecutionProjectionPort,
} from "../src/l3/l3-agent-entry.ts";
import { parseRustExecutionProjection } from "../src/l3/recovery/rust-execution-projection.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
};

function executionRuntime(events?: EventReplayLedger): AgentRuntime {
  return new AgentRuntime({
    decision: {
      async decide() {
        return { decisionId: "decision", actions: [], answer: "ok" };
      },
    },
    execution: {
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
    },
    events,
  });
}

function event(eventSeq: number): AgentRuntimeEvent {
  return {
    contractVersion: 1,
    eventSeq,
    type: "event_emitted",
    runId: `run-${eventSeq}`,
    traceId: `trace-${eventSeq}`,
    identity,
    data: { eventSeq },
    ts: eventSeq,
  };
}

function rustDocument(generation = 7, cleanShutdown = true): Record<string, unknown> {
  return {
    store_version: 1,
    generation,
    clean_shutdown: cleanShutdown,
    sessions: [
      {
        checkpoint_version: 1,
        snapshot: {
          contract_version: 1,
          spec: {
            session_id: identity.sessionId,
            agent_id: identity.agentId,
            cell_id: identity.cellId,
            role: "assistant",
            max_messages: 64,
          },
          state: cleanShutdown ? "active" : "crashed",
          next_input_seq: 3,
          next_message_seq: 5,
          clean_shutdown: cleanShutdown,
          messages: [
            {
              sequence: 1,
              input_seq: 1,
              message_id: "message-1",
              role: "user",
              content: "opaque body",
              created_at_ns: 10,
            },
          ],
        },
      },
    ],
    terminals: [
      {
        terminal_id: identity.terminalId,
        state: cleanShutdown ? "running" : "created",
        session_id: identity.sessionId,
        process_id: null,
        input_capacity: 64,
        output_capacity: 64,
        input_depth: 0,
        output_depth: 0,
        input_dropped: 0,
        output_dropped: 0,
      },
    ],
    loops: [
      {
        contract_version: 1,
        spec: {
          loop_id: "loop-1",
          agent_id: identity.agentId,
          cell_id: identity.cellId,
          session_id: identity.sessionId,
          terminal_id: identity.terminalId,
        },
        state: cleanShutdown ? "running" : "failed",
        next_command_seq: 9,
        accepted_commands: 8,
        failed_commands: 1,
        lock_wait_ns: 12,
      },
    ],
  };
}

function portFor(document: unknown): RustExecutionProjectionPort {
  return {
    authority: "rust",
    async load() {
      return structuredClone(document);
    },
  };
}

describe("Rust execution projection", () => {
  it("validates the checkpoint and strips message bodies and process handles", () => {
    const projection = parseRustExecutionProjection(rustDocument());
    expect(projection.generation).toBe(7);
    expect(projection.sessions[0]).toMatchObject({
      sessionId: identity.sessionId,
      retainedMessages: 1,
      nextInputSeq: 3,
    });
    expect(projection.terminals[0]).toMatchObject({
      terminalId: identity.terminalId,
      processBound: false,
    });
    expect(projection.loops[0]).toMatchObject({
      loopId: "loop-1",
      nextCommandSeq: 9,
    });
  });

  it("rejects unsupported versions, unsafe values, and oversized entity arrays", () => {
    const unsupported = rustDocument();
    unsupported.store_version = 2;
    expect(() => parseRustExecutionProjection(unsupported)).toThrow(/unsupported Rust execution-store version/);

    const unsafeGeneration = rustDocument();
    unsafeGeneration.generation = Number.MAX_SAFE_INTEGER + 1;
    expect(() => parseRustExecutionProjection(unsafeGeneration)).toThrow(/safe integer/);

    const oversized = rustDocument();
    oversized.sessions = Array.from({ length: 4097 }, () => rustDocument().sessions[0]);
    expect(() => parseRustExecutionProjection(oversized)).toThrow(/projection entity bound/);
  });
});

describe("L3A Rust-fenced session resume", () => {
  it("joins peer, Rust cursors, and replay events into a detached resume vector", async () => {
    const ledger = new EventReplayLedger();
    ledger.append(event(1));
    ledger.append(event(2));
    const peers = new L3APeerRouter({ runtime: executionRuntime(ledger) });
    peers.attach("peer-a", identity);
    const coordinator = new L3ASessionResumeCoordinator(peers, ledger, portFor(rustDocument()));

    const vector = await coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0, limit: 1 });
    expect(vector).toMatchObject({
      contractVersion: 1,
      peerId: "peer-a",
      generation: 7,
      status: "ready",
      continuity: {
        nextInputSeq: 3,
        nextMessageSeq: 5,
        nextCommandSeq: 9,
        nextEventSeq: 3,
      },
      session: { retainedMessages: 1, state: "active" },
      terminal: { terminalId: "terminal-1", processBound: false },
      loop: { loopId: "loop-1", acceptedCommands: 8 },
    });
    expect(vector.replay.events.map((item) => item.eventSeq)).toEqual([1]);
    vector.replay.events[0]!.data.eventSeq = 99;
    expect((await coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0 })).replay.events[0]!.data.eventSeq)
      .toBe(1);
    expect(coordinator.generation(identity)).toBe(7);
  });

  it("requires reactivation after an unclean Rust checkpoint", async () => {
    const ledger = new EventReplayLedger();
    const peers = new L3APeerRouter({ runtime: executionRuntime(ledger) });
    peers.attach("peer-a", identity);
    const coordinator = new L3ASessionResumeCoordinator(
      peers,
      ledger,
      portFor(rustDocument(8, false)),
    );

    const vector = await coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0 });
    expect(vector.status).toBe("requires_reactivation");
    expect(vector.cleanShutdown).toBe(false);
    expect(vector.session.state).toBe("crashed");
    expect(vector.loop.state).toBe("failed");
  });

  it("fences generation regressions and caller-provided optimistic generations", async () => {
    const ledger = new EventReplayLedger();
    const peers = new L3APeerRouter({ runtime: executionRuntime(ledger) });
    peers.attach("peer-a", identity);
    let current: unknown = rustDocument(9);
    const port: RustExecutionProjectionPort = {
      authority: "rust",
      async load() {
        return structuredClone(current);
      },
    };
    const coordinator = new L3ASessionResumeCoordinator(peers, ledger, port);

    await coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0 });
    await expect(
      coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0, expectedGeneration: 8 }),
    ).rejects.toMatchObject({ code: "recovery_stale" });

    current = rustDocument(8);
    await expect(coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0 }))
      .rejects.toMatchObject({ code: "recovery_stale" });
  });

  it("rejects missing or cross-wired Rust identities before peer handoff", async () => {
    const ledger = new EventReplayLedger();
    const peers = new L3APeerRouter({ runtime: executionRuntime(ledger) });
    peers.attach("peer-a", identity);
    const missing = rustDocument();
    missing.sessions = [];
    const coordinator = new L3ASessionResumeCoordinator(peers, ledger, portFor(missing));

    await expect(coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0 }))
      .rejects.toMatchObject({ code: "recovery_missing" });
    expect(peers.binding("peer-a")).toMatchObject({ state: "attached" });

    const crossWired = rustDocument();
    const sessions = crossWired.sessions as Array<Record<string, unknown>>;
    const snapshot = sessions[0]!.snapshot as Record<string, unknown>;
    const spec = snapshot.spec as Record<string, unknown>;
    spec.agent_id = "spoofed-agent";
    const crossCoordinator = new L3ASessionResumeCoordinator(peers, ledger, portFor(crossWired));
    await expect(crossCoordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0 }))
      .rejects.toMatchObject({ code: "recovery_invalid" });
  });

  it("preflights Rust and replay state before atomically handing a peer to a new ID", async () => {
    const ledger = new EventReplayLedger();
    const peers = new L3APeerRouter({ runtime: executionRuntime(ledger) });
    peers.attach("peer-a", identity);
    const coordinator = new L3ASessionResumeCoordinator(peers, ledger, portFor(rustDocument()));

    const vector = await coordinator.handoffAndResume({
      peerId: "peer-a",
      toPeerId: "peer-b",
      identity,
      afterEventSeq: 0,
    });
    expect(vector.peerId).toBe("peer-b");
    expect(peers.binding("peer-a")).toMatchObject({ state: "detached" });
    expect(peers.binding("peer-b")).toMatchObject({ state: "attached" });
    await expect(coordinator.resume({ peerId: "peer-a", identity, afterEventSeq: 0 }))
      .rejects.toMatchObject({ code: "peer_detached" });

    const failing = rustDocument();
    failing.sessions = [];
    await expect(
      new L3ASessionResumeCoordinator(peers, ledger, portFor(failing)).handoffAndResume({
        peerId: "peer-b",
        toPeerId: "peer-c",
        identity,
        afterEventSeq: 0,
      }),
    ).rejects.toMatchObject({ code: "recovery_missing" });
    expect(peers.binding("peer-b")).toMatchObject({ state: "attached" });
    expect(peers.binding("peer-c")).toBeNull();
  });
});
