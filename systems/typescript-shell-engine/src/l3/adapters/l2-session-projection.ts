/**
 * L3-to-L2 projection for TypeScript AgentRuntime events and results.
 *
 * L2 owns the session wire sequence and frontend replay surface. This adapter
 * translates detached L3 values into protocol-v1 messages while keeping
 * process, terminal, capability, and durable-state authority outside TS L3.
 */

import type { Message } from "../../protocol/wire-envelope.ts";
import { makeMessage, validateMessage } from "../../protocol/wire-envelope.ts";
import type { JsonObject } from "../../protocol/wire-records.ts";
import {
  AgentRuntimeError,
  copyAgentIdentity,
  copyJsonObject,
  type AgentEventSink,
  type AgentIdentity,
  type AgentInput,
  type AgentRuntimeEvent,
} from "../contracts/agent-contracts.ts";
import type { AgentRunResult } from "../runtime/ts-agent-runtime.ts";
import { L3_MAX_EVENT_DATA_BYTES, L3_MAX_REPLAY_EVENTS } from "../runtime/limits.ts";

const UTF8_ENCODER = new TextEncoder();

/** Sink for protocol-v1 messages owned by an L2 session host. */
export interface L2MessageSink {
  publish(message: Message): void | Promise<void>;
}

/** Session sequence authority supplied by the L2 session layer. */
export interface L2SessionSequencePort {
  next(sessionId: string): number;
}

/** Projection configuration; the adapter itself owns no session state. */
export interface L2SessionProjectionOptions {
  readonly sequence: L2SessionSequencePort;
  readonly sink?: L2MessageSink;
  readonly maxPayloadBytes?: number;
  readonly clock?: () => number;
}

/** Bounded in-memory sequence allocator for isolated L2 projection tests/hosts. */
export interface SessionSequenceAllocatorOptions {
  readonly maxSessions?: number;
}

function requireSessionId(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw new AgentRuntimeError("invalid_input", "sessionId must be a non-empty string without NUL");
  }
}

function requireSafeSequence(value: unknown, name: string): asserts value is number {
  if (!Number.isSafeInteger(value) || (value as number) < 1) {
    throw new AgentRuntimeError("invalid_input", `${name} must be a positive safe integer`);
  }
}

function jsonBytes(value: object): number {
  return UTF8_ENCODER.encode(JSON.stringify(value)).byteLength;
}

function copyAgentEvent(event: AgentRuntimeEvent): AgentRuntimeEvent {
  return {
    ...event,
    identity: copyAgentIdentity(event.identity),
    data: copyJsonObject(event.data),
  };
}

function identityData(identity: AgentIdentity): JsonObject {
  return {
    agent_id: identity.agentId,
    cell_id: identity.cellId,
    session_id: identity.sessionId,
    terminal_id: identity.terminalId,
  };
}

function validateProjectedMessage(message: Message, maxPayloadBytes: number): Message {
  if (jsonBytes(message.payload) > maxPayloadBytes) {
    throw new AgentRuntimeError("event_limit", "projected L2 payload exceeds the configured byte bound");
  }
  const errors = validateMessage(message);
  if (errors.length > 0) {
    throw new AgentRuntimeError("invalid_input", `projected L2 message is invalid: ${errors.join("; ")}`);
  }
  return message;
}

/**
 * Monotonic per-session output sequence allocator.
 *
 * The allocator is intentionally separate from the projection adapter so a
 * production L2 host can inject its own durable/session-authoritative source.
 */
export class SessionSequenceAllocator implements L2SessionSequencePort {
  private readonly nextBySession = new Map<string, number>();
  private readonly maxSessions: number;

  constructor(options: SessionSequenceAllocatorOptions = {}) {
    this.maxSessions = options.maxSessions ?? L3_MAX_REPLAY_EVENTS;
    if (!Number.isSafeInteger(this.maxSessions) || this.maxSessions < 1) {
      throw new TypeError("maxSessions must be a positive safe integer");
    }
  }

  /** Allocate the next positive protocol sequence for one session. */
  next(sessionId: string): number {
    requireSessionId(sessionId);
    const existing = this.nextBySession.get(sessionId);
    if (existing === undefined && this.nextBySession.size >= this.maxSessions) {
      throw new AgentRuntimeError("event_limit", "session sequence allocator bound exceeded");
    }
    const sequence = existing ?? 1;
    requireSafeSequence(sequence, "session sequence");
    if (sequence >= Number.MAX_SAFE_INTEGER) {
      throw new AgentRuntimeError("event_limit", "session sequence exhausted");
    }
    this.nextBySession.set(sessionId, sequence + 1);
    return sequence;
  }

  /** Forget one session sequence when the L2 host has retired that session. */
  clear(sessionId: string): void {
    requireSessionId(sessionId);
    this.nextBySession.delete(sessionId);
  }

  /** Return the number of tracked session sequences. */
  get size(): number {
    return this.nextBySession.size;
  }
}

/** Combine ordered AgentEventSink instances without leaking event aliases. */
export function fanoutAgentEventSinks(sinks: readonly AgentEventSink[]): AgentEventSink {
  const registered = sinks.filter((sink): sink is AgentEventSink => Boolean(sink));
  return {
    async publish(event: AgentRuntimeEvent): Promise<void> {
      for (const sink of registered) await sink.publish(copyAgentEvent(event));
    },
  };
}

/**
 * Translate L3 lifecycle events/results into L2 protocol-v1 messages.
 *
 * `publish()` implements AgentEventSink so it can be supplied directly to
 * AgentRuntime. `resultMessage()` and `failureMessage()` are explicit because
 * AgentRuntime results/failures are returned to the caller rather than sent
 * through the event sink.
 */
export class L2SessionProjection implements AgentEventSink {
  private readonly sequence: L2SessionSequencePort;
  private readonly sink?: L2MessageSink;
  private readonly maxPayloadBytes: number;
  private readonly clock: () => number;

  constructor(options: L2SessionProjectionOptions) {
    if (!options || typeof options !== "object" || !options.sequence) {
      throw new TypeError("L2SessionProjection requires an L2 session sequence port");
    }
    this.sequence = options.sequence;
    this.sink = options.sink;
    this.maxPayloadBytes = options.maxPayloadBytes ?? L3_MAX_EVENT_DATA_BYTES;
    if (!Number.isSafeInteger(this.maxPayloadBytes) || this.maxPayloadBytes < 1) {
      throw new TypeError("maxPayloadBytes must be a positive safe integer");
    }
    this.clock = options.clock ?? (() => Date.now() / 1000);
  }

  /** Convert one AgentRuntime lifecycle event to a detached L2 event message. */
  eventMessage(event: AgentRuntimeEvent): Message {
    const payload: JsonObject = {
      event_type: event.type,
      data: {
        event_seq: event.eventSeq,
        run_id: event.runId,
        identity: identityData(event.identity),
        details: copyJsonObject(event.data),
      },
    };
    const message = makeMessage(
      event.identity.sessionId,
      this.sequence.next(event.identity.sessionId),
      "event",
      payload,
      event.traceId,
      event.ts,
    );
    return validateProjectedMessage(message, this.maxPayloadBytes);
  }

  /** Convert one successful AgentRuntime result to a bounded L2 result. */
  resultMessage(input: AgentInput, result: AgentRunResult): Message {
    const payload: JsonObject = {
      success: true,
      output: result.answer,
      run_id: result.runId,
      action_count: result.actions,
      receipt_count: result.receipts.length,
      tool_result_count: result.toolResults.length,
      card_receipt_count: result.cardReceipts.length,
      schedule_receipt_count: result.scheduleReceipts.length,
      identity: identityData(input.identity),
    };
    const message = makeMessage(
      input.identity.sessionId,
      this.sequence.next(input.identity.sessionId),
      "result",
      payload,
      input.traceId,
      this.clock(),
    );
    return validateProjectedMessage(message, this.maxPayloadBytes);
  }

  /** Convert one failed AgentRuntime turn to a bounded L2 result envelope. */
  failureMessage(input: AgentInput, error: AgentRuntimeError): Message {
    const payload: JsonObject = {
      success: false,
      error: error.message,
      code: error.code,
      run_id: input.inputId,
      identity: identityData(input.identity),
    };
    const message = makeMessage(
      input.identity.sessionId,
      this.sequence.next(input.identity.sessionId),
      "result",
      payload,
      input.traceId,
      this.clock(),
    );
    return validateProjectedMessage(message, this.maxPayloadBytes);
  }

  /** Publish a lifecycle event to the injected L2 sink, if present. */
  async publish(event: AgentRuntimeEvent): Promise<void> {
    if (!this.sink) return;
    await this.sink.publish(this.eventMessage(event));
  }

  /** Publish a successful result to the injected L2 sink. */
  async publishResult(input: AgentInput, result: AgentRunResult): Promise<void> {
    if (!this.sink) return;
    await this.sink.publish(this.resultMessage(input, result));
  }

  /** Publish a failed result to the injected L2 sink. */
  async publishFailure(input: AgentInput, error: AgentRuntimeError): Promise<void> {
    if (!this.sink) return;
    await this.sink.publish(this.failureMessage(input, error));
  }
}
