/**
 * Public clean-break facade for the TypeScript L3 coordination domains.
 *
 * The coordinator joins L2 intent ingress, bounded Cell/AgentLoop admission,
 * and L3B cross-Cell forwarding without taking execution authority. Rust
 * remains the only owner of processes, terminals, capabilities, and hard
 * constraints; all of those dependencies are injected through AgentRuntime.
 */

import type { Message } from "../../protocol/wire-envelope.ts";
import type {
  AgentIdentity,
  AgentInput,
  AgentRuntimeErrorCode,
  AgentSnapshot,
} from "../contracts/agent-contracts.ts";
import { AgentRuntimeError, copyAgentIdentity, copyAgentInput } from "../contracts/agent-contracts.ts";
import type { AgentRunResult, AgentRuntime } from "../runtime/ts-agent-runtime.ts";
import { AgentCell } from "../cell/agent-cell.ts";
import { isAgentIdentity, type AgentLoopSnapshot } from "../loop/agent-loop-queue.ts";
import {
  CrossCellRouter,
  type CrossCellRegistration,
  type CrossCellRouteReceipt,
  type CrossCellRouteRequest,
} from "../routing/cross-cell-router.ts";
import { intentFromL2 } from "../adapters/l2-intent-adapter.ts";
import {
  L3_MAX_CROSS_CELL_HOPS,
  L3_MAX_REGISTERED_CELLS,
  L3_MAX_REPLAY_EVENTS,
} from "../runtime/limits.ts";

/** Maximum recent coordinator route latency samples retained for quantiles. */
export const L3_COORDINATOR_MAX_ROUTE_LATENCY_SAMPLES = L3_MAX_REPLAY_EVENTS * 4;

/** Payload-free route counters and bounded latency evidence. */
export interface L3CoordinatorRouteStats {
  readonly attempted: number;
  readonly delivered: number;
  readonly rejected: number;
  /** Rejections raised before target Cell admission (identity/bounds/registry). */
  readonly validationErrors: number;
  readonly active: number;
  readonly totalLatencyMs: number;
  readonly maxLatencyMs: number | null;
  readonly latencySampleCount: number;
  readonly latencySamplesDropped: number;
  /** Quantiles are computed over the retained recent sample window. */
  readonly p50LatencyMs: number | null;
  readonly p95LatencyMs: number | null;
  readonly p99LatencyMs: number | null;
}

/** Read-only view joining loop and runtime state for one identity. */
export interface L3CoordinatorSnapshot {
  readonly identity: AgentIdentity;
  readonly loop: AgentLoopSnapshot;
  readonly agent: AgentSnapshot | null;
}

/** Configuration for one independent L3 coordinator instance. */
export interface L3CoordinatorOptions {
  readonly runtime: AgentRuntime;
  readonly maxCells?: number;
  readonly maxHops?: number;
  readonly maxPendingInputs?: number;
  readonly maxRouteLatencySamples?: number;
  readonly clock?: () => number;
}

function quantile(sorted: readonly number[], fraction: number): number | null {
  if (sorted.length === 0) return null;
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1)] ?? null;
}

const ROUTE_VALIDATION_CODES: ReadonlySet<AgentRuntimeErrorCode> = new Set([
  "route_invalid",
  "route_conflict",
  "route_cell_not_found",
  "route_same_cell",
  "route_hop_limit",
  "route_limit",
]);

function isRouteValidationError(error: unknown): boolean {
  if (!(error instanceof AgentRuntimeError)) return false;
  return ROUTE_VALIDATION_CODES.has(error.code);
}

/** Bounded in-process metrics; no route payload or identity is retained. */
class CoordinatorRouteMetrics {
  private attempted = 0;
  private delivered = 0;
  private rejected = 0;
  private validationErrors = 0;
  private active = 0;
  private totalLatencyMs = 0;
  private maxLatencyMs: number | null = null;
  private readonly samples: number[] = [];
  private sampleCursor = 0;
  private samplesDropped = 0;

  constructor(
    private readonly maxSamples: number,
    private readonly now: () => number,
  ) {}

  begin(): number {
    this.attempted += 1;
    this.active += 1;
    return this.now();
  }

  validationError(): void {
    this.validationErrors += 1;
  }

  complete(started: number, status: "delivered" | "rejected"): void {
    this.active = Math.max(0, this.active - 1);
    if (status === "delivered") this.delivered += 1;
    else this.rejected += 1;
    const elapsed = Math.max(0, this.now() - started);
    this.totalLatencyMs += elapsed;
    this.maxLatencyMs = this.maxLatencyMs === null ? elapsed : Math.max(this.maxLatencyMs, elapsed);
    if (this.samples.length < this.maxSamples) {
      this.samples.push(elapsed);
      return;
    }
    this.samples[this.sampleCursor] = elapsed;
    this.sampleCursor = (this.sampleCursor + 1) % this.maxSamples;
    this.samplesDropped += 1;
  }

  snapshot(): L3CoordinatorRouteStats {
    const sorted = [...this.samples].sort((left, right) => left - right);
    return {
      attempted: this.attempted,
      delivered: this.delivered,
      rejected: this.rejected,
      validationErrors: this.validationErrors,
      active: this.active,
      totalLatencyMs: this.totalLatencyMs,
      maxLatencyMs: this.maxLatencyMs,
      latencySampleCount: this.samples.length,
      latencySamplesDropped: this.samplesDropped,
      p50LatencyMs: quantile(sorted, 0.5),
      p95LatencyMs: quantile(sorted, 0.95),
      p99LatencyMs: quantile(sorted, 0.99),
    };
  }
}

function validateCellId(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw new AgentRuntimeError("route_invalid", "cellId must be a non-empty string without NUL");
  }
}

function validateBoundedPositive(value: number, name: string, maximum: number): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new AgentRuntimeError("route_limit", `${name} must be a safe integer between 1 and ${maximum}`);
  }
  return value;
}

/**
 * Coordinates independent TypeScript L3 domains behind one explicit facade.
 *
 * The facade intentionally returns detached values and never exposes the
 * underlying Cell map. Registration constructs each Cell around the shared
 * AgentRuntime, with an optional per-Cell pending-input bound.
 */
export class L3Coordinator {
  private readonly runtime: AgentRuntime;
  private readonly router: CrossCellRouter;
  private readonly cells = new Map<string, AgentCell>();
  private readonly maxPendingInputs?: number;
  private readonly routeMetrics: CoordinatorRouteMetrics;

  constructor(options: L3CoordinatorOptions) {
    if (!options || typeof options !== "object" || !options.runtime) {
      throw new TypeError("L3Coordinator requires an AgentRuntime");
    }
    this.runtime = options.runtime;
    this.router = new CrossCellRouter({
      maxCells: options.maxCells ?? L3_MAX_REGISTERED_CELLS,
      maxHops: options.maxHops ?? L3_MAX_CROSS_CELL_HOPS,
    });
    const maxSamples = validateBoundedPositive(
      options.maxRouteLatencySamples ?? L3_COORDINATOR_MAX_ROUTE_LATENCY_SAMPLES,
      "maxRouteLatencySamples",
      L3_COORDINATOR_MAX_ROUTE_LATENCY_SAMPLES,
    );
    this.routeMetrics = new CoordinatorRouteMetrics(maxSamples, options.clock ?? (() => performance.now()));
    this.maxPendingInputs = options.maxPendingInputs;
  }

  /** Register a Cell, constructing a bounded Cell on first registration. */
  registerCell(
    cellId: string,
    options: { readonly maxPendingInputs?: number } = {},
  ): CrossCellRegistration {
    validateCellId(cellId);
    const existing = this.cells.get(cellId);
    if (existing) return { ...this.router.register(cellId, existing) };
    const cell = new AgentCell({
      runtime: this.runtime,
      maxPendingInputs: options.maxPendingInputs ?? this.maxPendingInputs,
    });
    const registration = this.router.register(cellId, cell);
    this.cells.set(cellId, cell);
    return { ...registration };
  }

  /** Remove a Cell registration without stopping its loops. */
  unregisterCell(cellId: string): boolean {
    validateCellId(cellId);
    const removed = this.router.unregister(cellId);
    if (removed) this.cells.delete(cellId);
    return removed;
  }

  /** Return deterministic Cell registration summaries. */
  registrations(): CrossCellRegistration[] {
    return this.router.registrations().map((registration) => ({ ...registration }));
  }

  /** Submit a normalized L3 input to its registered Cell. */
  submit(input: AgentInput, signal?: AbortSignal): Promise<AgentRunResult> {
    if (!input || typeof input !== "object" || !isAgentIdentity(input.identity)) {
      return Promise.reject(new AgentRuntimeError("invalid_input", "L3 coordinator input must contain an identity"));
    }
    const cellId = input.identity.cellId;
    const cell = this.cells.get(cellId);
    if (!cell) {
      return Promise.reject(new AgentRuntimeError("route_cell_not_found", `Cell is not registered: ${cellId}`));
    }
    return cell.submit(copyAgentInput(input), signal);
  }

  /** Convert one L2 intent envelope and submit it to the identity-bound Cell. */
  submitIntent(
    message: Message,
    identity: AgentIdentity,
    signal?: AbortSignal,
  ): Promise<AgentRunResult> {
    try {
      return this.submit(intentFromL2(message, copyAgentIdentity(identity)), signal);
    } catch (error) {
      return Promise.reject(error);
    }
  }

  /** Forward one validated input through the bounded L3B router. */
  async route(
    request: CrossCellRouteRequest,
    signal?: AbortSignal,
  ): Promise<CrossCellRouteReceipt> {
    const started = this.routeMetrics.begin();
    try {
      const receipt = await this.router.route(request, signal);
      this.routeMetrics.complete(started, receipt.status);
      return {
        ...receipt,
        source: copyAgentIdentity(receipt.source),
        target: copyAgentIdentity(receipt.target),
      };
    } catch (error) {
      if (isRouteValidationError(error)) this.routeMetrics.validationError();
      this.routeMetrics.complete(started, "rejected");
      throw error;
    }
  }

  /** Return a detached snapshot for one identity, or null when unknown. */
  snapshot(identity: AgentIdentity): L3CoordinatorSnapshot | null {
    if (!identity || typeof identity !== "object") return null;
    const cell = this.cells.get(identity.cellId);
    const loop = cell?.snapshot(identity);
    if (!loop) return null;
    return {
      identity: copyAgentIdentity(identity),
      loop,
      agent: this.runtime.snapshot(identity),
    };
  }

  /** Return deterministic snapshots across registered Cells. */
  snapshots(): L3CoordinatorSnapshot[] {
    const snapshots: L3CoordinatorSnapshot[] = [];
    for (const cell of this.cells.values()) {
      for (const loop of cell.snapshots()) {
        const snapshot = this.snapshot(loop.identity);
        if (snapshot) snapshots.push(snapshot);
      }
    }
    return snapshots.sort((left, right) => {
      const leftKey = JSON.stringify([
        left.identity.agentId,
        left.identity.cellId,
        left.identity.sessionId,
        left.identity.terminalId,
      ]);
      const rightKey = JSON.stringify([
        right.identity.agentId,
        right.identity.cellId,
        right.identity.sessionId,
        right.identity.terminalId,
      ]);
      return leftKey.localeCompare(rightKey);
    });
  }

  /** Return cumulative payload-free route metrics. */
  routeStats(): L3CoordinatorRouteStats {
    return this.routeMetrics.snapshot();
  }

  /** Stop one identity without affecting sibling loops. */
  stop(identity: AgentIdentity): void {
    this.cells.get(identity.cellId)?.stop(identity);
  }

  /** Drain every registered Cell, then retain registrations for inspection. */
  async drain(): Promise<void> {
    await this.router.drain();
  }

}
