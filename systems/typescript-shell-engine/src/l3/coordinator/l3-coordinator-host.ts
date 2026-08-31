/**
 * Composition root for the clean-break TypeScript L3 coordinator.
 *
 * This adapter wires the L3 runtime to the L2 session projection and the
 * bounded in-memory replay view. It does not implement transport, durable
 * outbox policy, process management, or terminal attachment; those remain
 * injected or Rust-owned concerns.
 */

import type { AgentEventSink } from "../contracts/agent-contracts.ts";
import {
  AgentRuntime,
  type AgentRuntimeOptions,
} from "../runtime/ts-agent-runtime.ts";
import {
  EventReplayLedger,
  type EventReplayLedgerOptions,
} from "../recovery/event-replay-ledger.ts";
import {
  fanoutAgentEventSinks,
  L2SessionProjection,
  type L2SessionProjectionOptions,
} from "../adapters/l2-session-projection.ts";
import {
  L3Coordinator,
  type L3CoordinatorOptions,
} from "./l3-coordinator.ts";

/** Runtime options accepted by the host adapter; event fanout is owned here. */
export type L3CoordinatorHostRuntimeOptions = Omit<AgentRuntimeOptions, "events"> & {
  readonly events?: AgentEventSink;
};

/** Options for composing L3 with an L2 session output boundary. */
export interface L3CoordinatorHostOptions {
  readonly runtime: L3CoordinatorHostRuntimeOptions;
  readonly sessionProjection: Omit<L2SessionProjectionOptions, "sink"> & {
    readonly sink: NonNullable<L2SessionProjectionOptions["sink"]>;
  };
  readonly replay?: EventReplayLedger;
  readonly replayOptions?: EventReplayLedgerOptions;
  readonly coordinator?: Omit<L3CoordinatorOptions, "runtime" | "sessionProjection">;
}

/** Fully wired clean-break L3 host surface. */
export interface L3CoordinatorHost {
  readonly runtime: AgentRuntime;
  readonly coordinator: L3Coordinator;
  readonly projection: L2SessionProjection;
  readonly replay: EventReplayLedger;
}

/**
 * Compose AgentRuntime, replay, L2 output projection, and coordinator.
 *
 * Event sinks are invoked in deterministic order: replay first, projection
 * second, then an optional external observer. Each sink receives a detached
 * event copy through `fanoutAgentEventSinks()`.
 */
export function createL3CoordinatorHost(options: L3CoordinatorHostOptions): L3CoordinatorHost {
  if (!options || typeof options !== "object") {
    throw new TypeError("L3CoordinatorHost options must be an object");
  }
  const replay = options.replay ?? new EventReplayLedger(options.replayOptions);
  const projection = new L2SessionProjection(options.sessionProjection);
  const sinks: AgentEventSink[] = [replay, projection];
  if (options.runtime.events) sinks.push(options.runtime.events);
  const runtime = new AgentRuntime({
    ...options.runtime,
    events: fanoutAgentEventSinks(sinks),
  });
  const coordinator = new L3Coordinator({
    ...options.coordinator,
    runtime,
    sessionProjection: projection,
  });
  return { runtime, coordinator, projection, replay };
}
