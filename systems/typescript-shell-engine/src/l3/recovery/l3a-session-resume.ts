/**
 * L3A session-resume coordinator over Rust execution projections.
 *
 * This module joins three bounded, detached views: the Rust-owned session /
 * terminal / AgentLoop checkpoint, the TypeScript replay ledger, and the
 * identity-safe peer router. It never writes checkpoints, replays side
 * effects, or exposes a process handle.
 */

import type {
  AgentIdentity,
  AgentRuntimeError,
  AgentRuntimeEvent,
} from "../contracts/agent-contracts.ts";
import {
  AgentRuntimeError as RuntimeError,
  L3_AGENT_CONTRACT_VERSION,
  copyAgentIdentity,
  copyJsonObject,
} from "../contracts/agent-contracts.ts";
import {
  agentIdentityKey,
  isAgentIdentity,
} from "../loop/agent-loop-queue.ts";
import { L3APeerRouter } from "../peer/l3a-peer-router.ts";
import {
  EventReplayLedger,
  type EventReplayResponse,
} from "./event-replay-ledger.ts";
import {
  copyRustIdentityProjection,
  parseRustExecutionProjection,
  projectRustIdentity,
  type RustIdentityProjection,
} from "./rust-execution-projection.ts";

/** Rust remains the only authority capable of reading durable execution state. */
export interface RustExecutionProjectionPort {
  readonly authority: "rust";
  /** Return one detached ExecutionStoreDocument or an equivalent JSON value. */
  load(identity: AgentIdentity, signal?: AbortSignal): Promise<unknown>;
}

/** Request for a generation-fenced L3A resume projection. */
export interface L3AResumeRequest {
  readonly peerId: string;
  readonly identity: AgentIdentity;
  readonly afterEventSeq: number;
  readonly limit?: number;
  /** Optional optimistic-concurrency fence for the Rust checkpoint generation. */
  readonly expectedGeneration?: number;
  readonly signal?: AbortSignal;
}

/** Request for a preflighted peer handoff followed by a resume projection. */
export interface L3APeerHandoffRequest extends L3AResumeRequest {
  readonly toPeerId: string;
}

/** Cursor values joining Rust session truth, loop state, and TS replay. */
export interface L3AResumeContinuity {
  readonly nextInputSeq: number;
  readonly nextMessageSeq: number;
  readonly nextCommandSeq: number;
  readonly nextEventSeq: number;
}

/** Stable status exposed to L2 without leaking Rust handles or payloads. */
export type L3ARecoveryStatus = "ready" | "requires_reactivation";

/** Detached L3A resume vector consumed by the L2 session projection. */
export interface L3AResumeVector {
  readonly contractVersion: typeof L3_AGENT_CONTRACT_VERSION;
  readonly peerId: string;
  readonly identity: AgentIdentity;
  readonly generation: number;
  readonly cleanShutdown: boolean;
  readonly status: L3ARecoveryStatus;
  readonly continuity: L3AResumeContinuity;
  readonly session: {
    readonly state: RustIdentityProjection["session"]["state"];
    readonly retainedMessages: number;
  };
  readonly terminal: {
    readonly terminalId: string;
    readonly state: RustIdentityProjection["terminal"]["state"];
    readonly processBound: boolean;
    readonly inputDepth: number;
    readonly outputDepth: number;
  };
  readonly loop: {
    readonly loopId: string;
    readonly state: RustIdentityProjection["loop"]["state"];
    readonly acceptedCommands: number;
    readonly failedCommands: number;
  };
  readonly replay: EventReplayResponse;
}

function invalid(message: string): AgentRuntimeError {
  return new RuntimeError("invalid_input", message);
}

function recoveryError(code: "recovery_stale" | "recovery_unavailable", message: string): AgentRuntimeError {
  return new RuntimeError(code, message);
}

function requirePeerId(value: unknown, name: string): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw invalid(`${name} must be a non-empty string`);
  }
}

function requireResumeRequest(request: L3AResumeRequest): void {
  if (!request || typeof request !== "object") throw invalid("resume request must be an object");
  requirePeerId(request.peerId, "peerId");
  if (!isAgentIdentity(request.identity)) throw invalid("resume identity must contain four non-empty fields");
  if (!Number.isSafeInteger(request.afterEventSeq) || request.afterEventSeq < 0) {
    throw invalid("afterEventSeq must be a non-negative safe integer");
  }
  if (
    request.limit !== undefined
    && (!Number.isSafeInteger(request.limit) || request.limit < 1)
  ) {
    throw invalid("resume limit must be a positive safe integer");
  }
  if (
    request.expectedGeneration !== undefined
    && (!Number.isSafeInteger(request.expectedGeneration) || request.expectedGeneration < 0)
  ) {
    throw invalid("expectedGeneration must be a non-negative safe integer");
  }
}

function copyReplay(replay: EventReplayResponse): EventReplayResponse {
  return {
    ...replay,
    identity: copyAgentIdentity(replay.identity),
    events: replay.events.map((event: AgentRuntimeEvent) => ({
      ...event,
      identity: copyAgentIdentity(event.identity),
      data: copyJsonObject(event.data),
    })),
  };
}

function recoveryStatus(projection: RustIdentityProjection): L3ARecoveryStatus {
  if (
    !projection.cleanShutdown
    || !projection.session.cleanShutdown
    || projection.session.state === "crashed"
    || projection.loop.state === "failed"
    || projection.terminal.state === "stopped"
    || projection.terminal.state === "closed"
  ) {
    return "requires_reactivation";
  }
  return "ready";
}

function vector(
  peerId: string,
  identity: AgentIdentity,
  projection: RustIdentityProjection,
  replay: EventReplayResponse,
): L3AResumeVector {
  const detached = copyRustIdentityProjection(projection);
  const status = recoveryStatus(detached);
  return {
    contractVersion: L3_AGENT_CONTRACT_VERSION,
    peerId,
    identity: copyAgentIdentity(identity),
    generation: detached.generation,
    cleanShutdown: detached.cleanShutdown,
    status,
    continuity: {
      nextInputSeq: detached.session.nextInputSeq,
      nextMessageSeq: detached.session.nextMessageSeq,
      nextCommandSeq: detached.loop.nextCommandSeq,
      nextEventSeq: replay.nextEventSeq,
    },
    session: {
      state: detached.session.state,
      retainedMessages: detached.session.retainedMessages,
    },
    terminal: {
      terminalId: detached.terminal.terminalId,
      state: detached.terminal.state,
      processBound: detached.terminal.processBound,
      inputDepth: detached.terminal.inputDepth,
      outputDepth: detached.terminal.outputDepth,
    },
    loop: {
      loopId: detached.loop.loopId,
      state: detached.loop.state,
      acceptedCommands: detached.loop.acceptedCommands,
      failedCommands: detached.loop.failedCommands,
    },
    replay: copyReplay(replay),
  };
}

/**
 * Coordinates peer resume without acquiring persistence or execution
 * authority. Generation observations are monotonic per complete identity.
 */
export class L3ASessionResumeCoordinator {
  private readonly generations = new Map<string, number>();

  constructor(
    private readonly peers: L3APeerRouter,
    private readonly replay: EventReplayLedger,
    private readonly rust: RustExecutionProjectionPort,
  ) {
    if (rust.authority !== "rust") {
      throw new RuntimeError("recovery_unavailable", "session recovery authority must be Rust");
    }
  }

  /** Load, validate, correlate, and replay one attached peer identity. */
  async resume(request: L3AResumeRequest): Promise<L3AResumeVector> {
    requireResumeRequest(request);
    this.requireAttachedPeer(request.peerId, request.identity);
    const projection = await this.loadIdentity(request);
    const replay = this.replay.resume({
      identity: copyAgentIdentity(request.identity),
      afterEventSeq: request.afterEventSeq,
      limit: request.limit,
    });
    return vector(request.peerId, request.identity, projection, replay);
  }

  /**
   * Preflight Rust and replay state, then atomically move the peer binding.
   *
   * The potentially failing asynchronous work completes before the handoff,
   * so a malformed or stale Rust projection cannot leave a half-moved route.
   */
  async handoffAndResume(request: L3APeerHandoffRequest): Promise<L3AResumeVector> {
    requireResumeRequest(request);
    requirePeerId(request.toPeerId, "toPeerId");
    this.requireAttachedPeer(request.peerId, request.identity);
    const projection = await this.loadIdentity(request);
    const replay = this.replay.resume({
      identity: copyAgentIdentity(request.identity),
      afterEventSeq: request.afterEventSeq,
      limit: request.limit,
    });
    this.peers.handoff(request.peerId, request.toPeerId, request.identity);
    return vector(request.toPeerId, request.identity, projection, replay);
  }

  /** Return the last accepted Rust generation for one identity, if observed. */
  generation(identity: AgentIdentity): number | null {
    if (!isAgentIdentity(identity)) return null;
    return this.generations.get(agentIdentityKey(identity)) ?? null;
  }

  private requireAttachedPeer(peerId: string, identity: AgentIdentity): void {
    const binding = this.peers.binding(peerId);
    if (!binding) throw new RuntimeError("peer_not_found", `unknown peer: ${peerId}`);
    if (binding.state !== "attached") {
      throw new RuntimeError("peer_detached", `peer is detached: ${peerId}`);
    }
    if (agentIdentityKey(binding.identity) !== agentIdentityKey(identity)) {
      throw new RuntimeError("peer_conflict", "resume identity does not match the peer binding");
    }
  }

  private async loadIdentity(request: L3AResumeRequest): Promise<RustIdentityProjection> {
    if (request.signal?.aborted) throw new RuntimeError("cancelled", "session resume was cancelled");
    let raw: unknown;
    try {
      raw = await this.rust.load(copyAgentIdentity(request.identity), request.signal);
    } catch (error) {
      if (error instanceof RuntimeError) throw error;
      throw recoveryError(
        "recovery_unavailable",
        error instanceof Error ? error.message : "Rust execution projection load failed",
      );
    }
    if (request.signal?.aborted) throw new RuntimeError("cancelled", "session resume was cancelled");

    let projection;
    try {
      projection = parseRustExecutionProjection(raw);
    } catch (error) {
      if (error instanceof RuntimeError) throw error;
      throw recoveryError("recovery_unavailable", "Rust execution projection parse failed");
    }
    const identityProjection = projectRustIdentity(projection, request.identity);
    const key = agentIdentityKey(request.identity);
    const previous = this.generations.get(key);
    if (
      request.expectedGeneration !== undefined
      && identityProjection.generation !== request.expectedGeneration
    ) {
      throw recoveryError(
        "recovery_stale",
        `Rust execution generation changed (expected ${request.expectedGeneration}, got ${identityProjection.generation})`,
      );
    }
    if (previous !== undefined && identityProjection.generation < previous) {
      throw recoveryError(
        "recovery_stale",
        `Rust execution generation regressed (previous ${previous}, got ${identityProjection.generation})`,
      );
    }
    this.generations.set(key, identityProjection.generation);
    return identityProjection;
  }
}
