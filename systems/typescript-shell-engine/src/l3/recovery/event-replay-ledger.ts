/**
 * Bounded L3 lifecycle replay ledger.
 *
 * This module is a clean-break recovery projection. It keeps only detached
 * AgentRuntime events in memory so an L2 view can resume from a cursor. Rust
 * remains authoritative for durable session/terminal/AgentLoop state; this
 * ledger never writes checkpoints or replays side effects.
 */

import type {
  AgentEventSink,
  AgentIdentity,
  AgentRuntimeEvent,
  AgentRuntimeErrorCode,
} from "../contracts/agent-contracts.ts";
import {
  AgentRuntimeError,
  L3_AGENT_CONTRACT_VERSION,
  copyAgentIdentity,
  copyJsonObject,
} from "../contracts/agent-contracts.ts";
import { agentIdentityKey, isAgentIdentity } from "../loop/agent-loop-queue.ts";
import { L3_MAX_REPLAY_EVENTS } from "../runtime/limits.ts";

/** Options for the in-memory, per-identity replay window. */
export interface EventReplayLedgerOptions {
  readonly maxEventsPerIdentity?: number;
}

/** Request for a bounded cursor-based lifecycle replay. */
export interface EventReplayRequest {
  readonly identity: AgentIdentity;
  readonly afterEventSeq: number;
  readonly limit?: number;
}

/** Response returned to an L2/L3A recovery projection. */
export interface EventReplayResponse {
  readonly contractVersion: typeof L3_AGENT_CONTRACT_VERSION;
  readonly identity: AgentIdentity;
  readonly afterEventSeq: number;
  readonly oldestEventSeq: number | null;
  readonly nextEventSeq: number;
  readonly events: readonly AgentRuntimeEvent[];
  readonly hasMore: boolean;
  readonly requiresResync: boolean;
}

/** Detached state summary for one identity's replay window. */
export interface EventReplaySnapshot {
  readonly identity: AgentIdentity;
  readonly retainedEvents: number;
  readonly oldestEventSeq: number | null;
  readonly latestEventSeq: number | null;
  readonly nextEventSeq: number;
}

interface ReplayWindow {
  readonly identity: AgentIdentity;
  readonly events: AgentRuntimeEvent[];
  nextEventSeq: number;
}

const EVENT_TYPES: readonly AgentRuntimeEvent["type"][] = [
  "run_started",
  "decision_ready",
  "kernel_request_submitted",
  "kernel_request_completed",
  "tool_call_submitted",
  "tool_result_completed",
  "card_intent_submitted",
  "card_intent_completed",
  "schedule_request_submitted",
  "schedule_request_completed",
  "event_emitted",
  "run_completed",
  "run_failed",
];

function invalid(code: AgentRuntimeErrorCode, message: string): AgentRuntimeError {
  return new AgentRuntimeError(code, message);
}

function requireIdentity(identity: unknown): asserts identity is AgentIdentity {
  if (!isAgentIdentity(identity)) {
    throw invalid("invalid_input", "replay identity must contain four non-empty fields");
  }
}

function requirePositiveLimit(value: unknown, name: string, maximum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > maximum) {
    throw invalid("replay_limit", `${name} must be a safe integer between 1 and ${maximum}`);
  }
  return value as number;
}

function requireCursor(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw invalid("replay_gap", "afterEventSeq must be a non-negative safe integer");
  }
  return value as number;
}

function isJsonValue(value: unknown, ancestors: WeakSet<object> = new WeakSet<object>()): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "object" || ancestors.has(value)) return false;
  ancestors.add(value);
  const valid = Array.isArray(value)
    ? value.every((item) => isJsonValue(item, ancestors))
    : (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
      && Object.values(value).every((item) => isJsonValue(item, ancestors));
  ancestors.delete(value);
  return valid;
}

function cloneEvent(event: AgentRuntimeEvent): AgentRuntimeEvent {
  return {
    ...event,
    identity: copyAgentIdentity(event.identity),
    data: copyJsonObject(event.data),
  };
}

function validateEvent(event: AgentRuntimeEvent): void {
  if (!event || typeof event !== "object") {
    throw invalid("invalid_input", "replay event must be an object");
  }
  if (event.contractVersion !== L3_AGENT_CONTRACT_VERSION) {
    throw invalid("invalid_input", `unsupported replay event contract: ${String(event.contractVersion)}`);
  }
  requireIdentity(event.identity);
  if (!Number.isSafeInteger(event.eventSeq) || event.eventSeq < 1) {
    throw invalid("replay_gap", "eventSeq must be a positive safe integer");
  }
  if (
    typeof event.runId !== "string"
    || typeof event.traceId !== "string"
    || !(EVENT_TYPES as readonly string[]).includes(event.type)
  ) {
    throw invalid("invalid_input", "replay event identifiers and type must be strings");
  }
  if (typeof event.ts !== "number" || !Number.isFinite(event.ts)) {
    throw invalid("invalid_input", "replay event timestamp must be finite");
  }
  if (!event.data || typeof event.data !== "object" || Array.isArray(event.data) || !isJsonValue(event.data)) {
    throw invalid("invalid_input", "replay event data must be a finite JSON object");
  }
}

/**
 * Bounded event ledger that also implements the AgentEventSink contract.
 *
 * Events are required to be contiguous per identity. That makes a dropped
 * prefix observable during resume instead of silently presenting a partial
 * history as complete.
 */
export class EventReplayLedger implements AgentEventSink {
  private readonly windows = new Map<string, ReplayWindow>();
  private readonly maxEventsPerIdentity: number;

  constructor(options: EventReplayLedgerOptions = {}) {
    this.maxEventsPerIdentity = options.maxEventsPerIdentity ?? L3_MAX_REPLAY_EVENTS;
    requirePositiveLimit(this.maxEventsPerIdentity, "maxEventsPerIdentity", Number.MAX_SAFE_INTEGER);
  }

  /** Append one lifecycle event after sequence and identity validation. */
  append(event: AgentRuntimeEvent): void {
    validateEvent(event);
    const key = agentIdentityKey(event.identity);
    const window = this.windows.get(key);
    if (!window) {
      if (event.eventSeq !== 1) {
        throw invalid("replay_gap", `first replay event must start at sequence 1 (got ${event.eventSeq})`);
      }
      this.windows.set(key, {
        identity: copyAgentIdentity(event.identity),
        events: [cloneEvent(event)],
        nextEventSeq: 2,
      });
      return;
    }
    if (event.eventSeq !== window.nextEventSeq) {
      throw invalid(
        "replay_gap",
        `replay event sequence must be contiguous (expected ${window.nextEventSeq}, got ${event.eventSeq})`,
      );
    }
    window.events.push(cloneEvent(event));
    window.nextEventSeq += 1;
    if (window.events.length > this.maxEventsPerIdentity) window.events.shift();
  }

  /** AgentEventSink implementation used by AgentRuntime. */
  publish(event: AgentRuntimeEvent): void {
    this.append(event);
  }

  /** Return a bounded replay response for one full identity. */
  resume(request: EventReplayRequest): EventReplayResponse {
    if (!request || typeof request !== "object") {
      throw invalid("invalid_input", "replay request must be an object");
    }
    requireIdentity(request?.identity);
    const afterEventSeq = requireCursor(request.afterEventSeq);
    const limit = request.limit ?? this.maxEventsPerIdentity;
    requirePositiveLimit(limit, "limit", this.maxEventsPerIdentity);
    const key = agentIdentityKey(request.identity);
    const window = this.windows.get(key);
    const events = window?.events ?? [];
    const nextEventSeq = window?.nextEventSeq ?? 1;
    const oldestEventSeq = events[0]?.eventSeq ?? null;
    if (afterEventSeq >= nextEventSeq) {
      throw invalid(
        "replay_gap",
        `replay cursor ${afterEventSeq} is ahead of the next event sequence ${nextEventSeq}`,
      );
    }
    const requiresResync = oldestEventSeq !== null && afterEventSeq < oldestEventSeq - 1;
    const selected = events.filter((event) => event.eventSeq > afterEventSeq).slice(0, limit).map(cloneEvent);
    return {
      contractVersion: L3_AGENT_CONTRACT_VERSION,
      identity: copyAgentIdentity(request.identity),
      afterEventSeq,
      oldestEventSeq,
      nextEventSeq,
      events: selected,
      hasMore: selected.length > 0 && selected[selected.length - 1].eventSeq < nextEventSeq - 1,
      requiresResync,
    };
  }

  /** Return a detached summary for one identity, or null when unseen. */
  snapshot(identity: AgentIdentity): EventReplaySnapshot | null {
    requireIdentity(identity);
    const window = this.windows.get(agentIdentityKey(identity));
    if (!window) return null;
    return {
      identity: copyAgentIdentity(window.identity),
      retainedEvents: window.events.length,
      oldestEventSeq: window.events[0]?.eventSeq ?? null,
      latestEventSeq: window.events[window.events.length - 1]?.eventSeq ?? null,
      nextEventSeq: window.nextEventSeq,
    };
  }

  /** Return detached snapshots in deterministic identity order. */
  snapshots(): EventReplaySnapshot[] {
    return [...this.windows.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([, window]) => this.snapshot(window.identity)!);
  }

  /** Remove one in-memory replay window; durable Rust state is untouched. */
  clear(identity: AgentIdentity): void {
    requireIdentity(identity);
    this.windows.delete(agentIdentityKey(identity));
  }
}
