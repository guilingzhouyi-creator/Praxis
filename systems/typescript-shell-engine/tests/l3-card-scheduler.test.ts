import { describe, expect, it } from "vitest";
import {
  AgentRuntime,
  AgentRuntimeError,
  type AgentDecisionPort,
  type AgentIdentity,
  type AgentInput,
  type CardIntent,
  type CardIntentReceipt,
  type KernelExecutionRequest,
  type RustKernelExecutionPort,
  type ScheduleReceipt,
  type ScheduleRequest,
} from "../src/l3/l3-agent-entry.ts";

const identity: AgentIdentity = {
  agentId: "agent-card",
  cellId: "cell-card",
  sessionId: "session-card",
  terminalId: "terminal-card",
};

function input(inputId = "session-card:1"): AgentInput {
  return {
    inputId,
    inputSeq: 1,
    text: "plan a bounded card run",
    traceId: "trace-card",
    identity,
  };
}

const rustExecution: RustKernelExecutionPort = {
  authority: "rust",
  async submit(request: KernelExecutionRequest) {
    return {
      receiptId: `receipt-${request.requestId}`,
      requestId: request.requestId,
      accepted: true,
      status: "completed",
      traceId: request.traceId,
    };
  },
};

function coordinationPort(
  cards: CardIntent[],
  schedules: ScheduleRequest[],
): {
  readonly card: {
    readonly authority: "typescript";
    submitCardIntent(intent: CardIntent): Promise<CardIntentReceipt>;
  };
  readonly scheduler: {
    readonly authority: "typescript";
    submitScheduleRequest(request: ScheduleRequest): Promise<ScheduleReceipt>;
  };
} {
  return {
    card: {
      authority: "typescript",
      async submitCardIntent(intent) {
        cards.push(intent);
        return {
          intentId: intent.intentId,
          cardId: intent.cardId,
          traceId: intent.traceId,
          accepted: true,
          status: "accepted",
          data: { owner: "ts-l3" },
        };
      },
    },
    scheduler: {
      authority: "typescript",
      async submitScheduleRequest(request) {
        schedules.push(request);
        return {
          requestId: request.requestId,
          taskId: request.taskId,
          traceId: request.traceId,
          accepted: true,
          status: "queued",
          position: 0,
        };
      },
    },
  };
}

describe("TS L3 card and scheduler coordination", () => {
  it("binds card and schedule actions to the full identity and returns detached receipts", async () => {
    const cards: CardIntent[] = [];
    const schedules: ScheduleRequest[] = [];
    const decision: AgentDecisionPort = {
      async decide() {
        return {
          decisionId: "decision-card-schedule",
          answer: "queued",
          actions: [
            {
              kind: "card_intent",
              actionId: "card-intent-1",
              cardId: "card-1",
              operation: "produce",
              title: "Investigate the bounded bridge",
              lifecycle: "draft",
              links: {
                skillIds: ["skill-review"],
                todoIds: ["todo-1"],
                evidenceRefs: ["evidence-1"],
              },
              data: { mode: "analysis" },
            },
            {
              kind: "schedule_request",
              actionId: "schedule-1",
              taskId: "task-1",
              queue: "interactive",
              priority: 10,
              notBefore: 100,
              deadline: 200,
              scope: "agent",
              estimatedCost: 3,
              metadata: { source: "card-1" },
            },
          ],
        };
      },
    };
    const runtime = new AgentRuntime({
      decision,
      execution: rustExecution,
      coordination: coordinationPort(cards, schedules),
    });

    const result = await runtime.run(input());

    expect(result.cardReceipts).toHaveLength(1);
    expect(result.scheduleReceipts).toHaveLength(1);
    expect(cards[0]).toMatchObject({
      intentId: "card-intent-1",
      cardId: "card-1",
      identity,
      traceId: "trace-card",
      links: { skillIds: ["skill-review"], todoIds: ["todo-1"], evidenceRefs: ["evidence-1"] },
    });
    expect(schedules[0]).toMatchObject({
      requestId: "schedule-1",
      taskId: "task-1",
      identity,
      traceId: "trace-card",
      deadline: 200,
    });
    expect(result.actions).toBe(2);
  });

  it("fails closed when a coordination action has no injected port", async () => {
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return {
            decisionId: "decision-no-port",
            actions: [{
              kind: "card_intent",
              actionId: "card-intent-no-port",
              cardId: "card-2",
              operation: "approve",
            }],
          };
        },
      },
      execution: rustExecution,
    });

    await expect(runtime.run(input("session-card:2"))).rejects.toMatchObject({
      code: "coordination_failed",
    });
  });

  it("rejects duplicate card links and inverted scheduler deadlines before host calls", async () => {
    const cards: CardIntent[] = [];
    const schedules: ScheduleRequest[] = [];
    const calls = { card: 0, schedule: 0 };
    const port = coordinationPort(cards, schedules);
    const guardedPort = {
      card: {
        authority: "typescript" as const,
        async submitCardIntent(intent: CardIntent) {
          calls.card += 1;
          return port.card.submitCardIntent(intent);
        },
      },
      scheduler: {
        authority: "typescript" as const,
        async submitScheduleRequest(request: ScheduleRequest) {
          calls.schedule += 1;
          return port.scheduler.submitScheduleRequest(request);
        },
      },
    };
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return {
            decisionId: "decision-invalid-links",
            actions: [{
              kind: "card_intent",
              actionId: "card-intent-invalid",
              cardId: "card-3",
              operation: "execute",
              links: { skillIds: ["same", "same"], todoIds: [], evidenceRefs: [] },
            }],
          };
        },
      },
      execution: rustExecution,
      coordination: guardedPort,
    });

    await expect(runtime.run(input("session-card:3"))).rejects.toMatchObject({
      code: "invalid_coordination",
    });
    expect(calls.card).toBe(0);

    const scheduleRuntime = new AgentRuntime({
      decision: {
        async decide() {
          return {
            decisionId: "decision-invalid-deadline",
            actions: [{
              kind: "schedule_request",
              actionId: "schedule-invalid",
              taskId: "task-invalid",
              queue: "interactive",
              priority: 1,
              notBefore: 50,
              deadline: 10,
              scope: "session",
            }],
          };
        },
      },
      execution: rustExecution,
      coordination: guardedPort,
    });
    await expect(scheduleRuntime.run(input("session-card:4"))).rejects.toMatchObject({
      code: "invalid_coordination",
    });
    expect(calls.schedule).toBe(0);
  });

  it("does not expose mutable provider-owned coordination payloads", async () => {
    const cards: CardIntent[] = [];
    const schedules: ScheduleRequest[] = [];
    const source = {
      kind: "card_intent" as const,
      actionId: "card-detached",
      cardId: "card-4",
      operation: "produce" as const,
      title: "detached",
      links: { skillIds: ["skill-1"], todoIds: [], evidenceRefs: [] },
      data: { nested: { value: 1 } },
    };
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return { decisionId: "decision-detached", actions: [source] };
        },
      },
      execution: rustExecution,
      coordination: coordinationPort(cards, schedules),
    });

    await runtime.run(input("session-card:5"));
    source.links.skillIds[0] = "mutated";
    (source.data!.nested as { value: number }).value = 9;
    expect(cards[0].links.skillIds).toEqual(["skill-1"]);
    expect(cards[0].data).toEqual({ nested: { value: 1 } });
  });

  it("maps a rejected scheduler receipt to a coordination rejection", async () => {
    const runtime = new AgentRuntime({
      decision: {
        async decide() {
          return {
            decisionId: "decision-reject-schedule",
            actions: [{
              kind: "schedule_request",
              actionId: "schedule-rejected",
              taskId: "task-rejected",
              queue: "background",
              priority: 2,
              notBefore: 0,
              scope: "cell",
            }],
          };
        },
      },
      execution: rustExecution,
      coordination: {
        card: {
          authority: "typescript",
          async submitCardIntent() {
            throw new AgentRuntimeError("coordination_failed", "unexpected card request");
          },
        },
        scheduler: {
          authority: "typescript",
          async submitScheduleRequest(request) {
            return {
              requestId: request.requestId,
              taskId: request.taskId,
              traceId: request.traceId,
              accepted: false,
              status: "rejected",
              error: "queue full",
            };
          },
        },
      },
    });

    await expect(runtime.run(input("session-card:6"))).rejects.toMatchObject({
      code: "coordination_rejected",
    });
  });
});
