import { describe, expect, it } from "vitest";
import {
  AgentRuntime,
  EventReplayLedger,
  L3APeerRouter,
  type AgentIdentity,
  type AgentRuntimeEvent,
  type KernelExecutionRequest,
  type RustKernelExecutionPort,
} from "../src/l3/l3-agent-entry.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
};

function event(eventSeq: number, currentIdentity: AgentIdentity = identity): AgentRuntimeEvent {
  return {
    contractVersion: 1,
    eventSeq,
    type: "event_emitted",
    runId: `run-${eventSeq}`,
    traceId: `trace-${eventSeq}`,
    identity: currentIdentity,
    data: { value: eventSeq },
    ts: eventSeq,
  };
}

function input(inputSeq: number, currentIdentity: AgentIdentity = identity) {
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

function runtime(events?: EventReplayLedger): AgentRuntime {
  return new AgentRuntime({
    decision: {
      async decide(currentInput) {
        return {
          decisionId: `decision-${currentInput.inputSeq}`,
          actions: [],
          answer: `answer-${currentInput.inputSeq}`,
        };
      },
    },
    execution: executionPort(),
    events,
  });
}

describe("TypeScript L3 replay ledger", () => {
  it("bounds per-identity history and exposes cursor pagination", () => {
    const ledger = new EventReplayLedger({ maxEventsPerIdentity: 2 });
    ledger.append(event(1));
    ledger.append(event(2));
    ledger.append(event(3));

    expect(ledger.snapshot(identity)).toMatchObject({
      retainedEvents: 2,
      oldestEventSeq: 2,
      latestEventSeq: 3,
      nextEventSeq: 4,
    });

    const page = ledger.resume({ identity, afterEventSeq: 1, limit: 1 });
    expect(page.events.map((item) => item.eventSeq)).toEqual([2]);
    expect(page.hasMore).toBe(true);
    expect(page.requiresResync).toBe(false);

    const gap = ledger.resume({ identity, afterEventSeq: 0 });
    expect(gap.events.map((item) => item.eventSeq)).toEqual([2, 3]);
    expect(gap.requiresResync).toBe(true);

    (gap.events[0].data as { value: number }).value = 99;
    expect(ledger.resume({ identity, afterEventSeq: 1 }).events[0].data.value).toBe(2);
  });

  it("rejects non-contiguous events and future cursors fail closed", () => {
    const ledger = new EventReplayLedger();
    expect(() => ledger.append(event(2))).toThrow(/start at sequence 1/);
    ledger.append(event(1));
    expect(() => ledger.append(event(1))).toThrow(/contiguous/);
    expect(() => ledger.append(event(3))).toThrow(/contiguous/);
    expect(() => ledger.resume({ identity, afterEventSeq: 2 })).toThrow(/ahead/);

    const unseen = { ...identity, sessionId: "unseen" };
    expect(ledger.resume({ identity: unseen, afterEventSeq: 0 }).events).toEqual([]);
    expect(() => ledger.resume({ identity: unseen, afterEventSeq: 1 })).toThrow(/ahead/);
  });

  it("rejects unknown event kinds and cyclic payloads at the replay boundary", () => {
    const ledger = new EventReplayLedger();
    expect(() => ledger.append({ ...event(1), type: "unknown" as never })).toThrow(/identifiers and type/);
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    expect(() => ledger.append({ ...event(1), data: cyclic as never })).toThrow(/finite JSON object/);
  });

  it("keeps replay windows isolated by the complete identity tuple", () => {
    const ledger = new EventReplayLedger();
    const sibling = { ...identity, terminalId: "terminal-2" };
    ledger.append(event(1, identity));
    ledger.append(event(1, sibling));

    expect(ledger.snapshots().map((snapshot) => snapshot.identity.terminalId)).toEqual([
      "terminal-1",
      "terminal-2",
    ]);
    expect(ledger.resume({ identity: sibling, afterEventSeq: 0 }).events[0].identity).toEqual(sibling);
  });
});

describe("TypeScript L3A peer router", () => {
  it("routes attached identities and records runtime events for resume", async () => {
    const ledger = new EventReplayLedger();
    const router = new L3APeerRouter({ runtime: runtime(ledger) });
    router.attach("peer-a", identity);

    const result = await router.submit(input(1));
    expect(result.answer).toBe("answer-1");
    expect(router.binding("peer-a")).toMatchObject({ state: "attached", peerId: "peer-a" });
    expect(ledger.resume({ identity, afterEventSeq: 0 }).events.map((item) => item.type)).toEqual([
      "run_started",
      "decision_ready",
      "run_completed",
    ]);
  });

  it("prevents identity conflicts and stale peer submissions", async () => {
    const router = new L3APeerRouter({ runtime: runtime() });
    router.attach("peer-a", identity);
    expect(() => router.attach("peer-b", identity)).toThrow(/already bound/);
    const sibling = { ...identity, terminalId: "terminal-2" };
    await expect(router.submitTo("peer-a", input(1, sibling))).rejects.toMatchObject({ code: "peer_conflict" });

    router.detach("peer-a");
    expect(router.binding("peer-a")).toMatchObject({ state: "detached" });
    await expect(router.submitTo("peer-a", input(2))).rejects.toMatchObject({ code: "peer_detached" });
    await expect(router.submit(input(2))).rejects.toMatchObject({ code: "peer_not_found" });
  });

  it("drains a peer before detaching and preserves deterministic bindings", async () => {
    const router = new L3APeerRouter({ runtime: runtime() });
    const sibling = { ...identity, sessionId: "session-2" };
    router.attach("peer-b", sibling);
    router.attach("peer-a", identity);

    await router.drain("peer-a");
    await expect(router.submitTo("peer-a", input(1))).rejects.toMatchObject({ code: "peer_detached" });
    expect(router.bindings().map((binding) => binding.peerId)).toEqual(["peer-a", "peer-b"]);
    expect(router.binding("peer-a")).toMatchObject({ state: "detached" });
    await expect(router.submit(input(1))).rejects.toMatchObject({ code: "peer_not_found" });
  });
});
