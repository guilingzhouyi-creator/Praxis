/**
 * Bounded L3B cross-Cell routing for the TypeScript rewrite.
 *
 * This domain forwards a validated AgentInput between independently-owned
 * AgentCell coordinators. It keeps only Cell references and detached route
 * receipts; Rust remains the sole process, terminal, capability, and
 * hard-constraint authority.
 */

import type { JsonObject } from "../../protocol/wire-records.ts";
import type {
  AgentIdentity,
  AgentInput,
  AgentRuntimeError,
  AgentRuntimeErrorCode,
} from "../contracts/agent-contracts.ts";
import {
  AgentRuntimeError as RuntimeError,
  L3_AGENT_CONTRACT_VERSION,
  copyAgentIdentity,
  copyAgentInput,
  copyJsonObject,
} from "../contracts/agent-contracts.ts";
import type { AgentRunResult } from "../runtime/ts-agent-runtime.ts";
import type { AgentCell } from "../cell/agent-cell.ts";
import {
  L3_MAX_CROSS_CELL_HOPS,
  L3_MAX_REGISTERED_CELLS,
  L3_MAX_ROUTE_ID_BYTES,
  L3_MAX_ROUTE_METADATA_BYTES,
} from "../runtime/limits.ts";
import { agentIdentityKey, isAgentIdentity } from "../loop/agent-loop-queue.ts";

/** A validated request to forward one input across Cell boundaries. */
export interface CrossCellRouteRequest {
  readonly routeId: string;
  readonly traceId: string;
  readonly source: AgentIdentity;
  readonly target: AgentIdentity;
  readonly input: AgentInput;
  /** Number of already-completed forwarding hops, defaulting to zero. */
  readonly hops?: number;
  /** Optional bounded routing metadata; payload text stays in AgentInput. */
  readonly metadata?: JsonObject;
}

/** Detached route outcome returned after target Cell admission settles. */
export interface CrossCellRouteReceipt {
  readonly contractVersion: typeof L3_AGENT_CONTRACT_VERSION;
  readonly routeId: string;
  readonly traceId: string;
  readonly source: AgentIdentity;
  readonly target: AgentIdentity;
  readonly hops: number;
  readonly status: "delivered" | "rejected";
  readonly result?: AgentRunResult;
  readonly error?: {
    readonly code: AgentRuntimeErrorCode;
    readonly message: string;
  };
  readonly metadata?: JsonObject;
}

/** Read-only Cell registration summary without exposing an execution handle. */
export interface CrossCellRegistration {
  readonly cellId: string;
  readonly loopCount: number;
}

/** Router configuration for bounded Cell registration and route hops. */
export interface CrossCellRouterOptions {
  readonly maxCells?: number;
  readonly maxHops?: number;
}

function invalid(code: AgentRuntimeErrorCode, message: string): AgentRuntimeError {
  return new RuntimeError(code, message);
}

function routeText(value: unknown, name: string, maxBytes: number): string {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw invalid("route_invalid", `${name} must be a non-empty string without NUL`);
  }
  if (new TextEncoder().encode(value).byteLength > maxBytes) {
    throw invalid("route_limit", `${name} exceeds the configured byte bound`);
  }
  return value;
}

function safeBoundedInteger(value: unknown, name: string, minimum: number, maximum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw invalid("route_invalid", `${name} must be a safe integer between ${minimum} and ${maximum}`);
  }
  return value as number;
}

function isFiniteJson(value: unknown, ancestors: WeakSet<object> = new WeakSet<object>()): value is JsonObject {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "object" || ancestors.has(value)) return false;
  if (Array.isArray(value)) {
    ancestors.add(value);
    const valid = value.every((item) => isFiniteJson(item, ancestors));
    ancestors.delete(value);
    return valid;
  }
  const record = value as Record<string, unknown>;
  if (Object.getPrototypeOf(record) !== Object.prototype && Object.getPrototypeOf(record) !== null) return false;
  ancestors.add(record);
  const valid = Object.values(record).every((item) => {
    return isFiniteJson(item, ancestors);
  });
  ancestors.delete(record);
  return valid;
}

function copyRunResult(result: AgentRunResult): AgentRunResult {
  return {
    ...result,
    identity: copyAgentIdentity(result.identity),
    receipts: result.receipts.map((receipt) => ({
      ...receipt,
      data: receipt.data ? copyJsonObject(receipt.data) : undefined,
    })),
    toolResults: result.toolResults.map((toolResult) => ({
      ...toolResult,
      data: toolResult.data ? copyJsonObject(toolResult.data) : undefined,
    })),
    cardReceipts: result.cardReceipts.map((receipt) => ({
      ...receipt,
      data: receipt.data ? copyJsonObject(receipt.data) : undefined,
    })),
    scheduleReceipts: result.scheduleReceipts.map((receipt) => ({ ...receipt })),
  };
}

function rejectedReceipt(
  request: CrossCellRouteRequest,
  hops: number,
  error: AgentRuntimeError,
): CrossCellRouteReceipt {
  return {
    contractVersion: L3_AGENT_CONTRACT_VERSION,
    routeId: request.routeId,
    traceId: request.traceId,
    source: copyAgentIdentity(request.source),
    target: copyAgentIdentity(request.target),
    hops,
    status: "rejected",
    error: { code: error.code, message: error.message },
    metadata: request.metadata ? copyJsonObject(request.metadata) : undefined,
  };
}

function validateRequest(request: CrossCellRouteRequest, maxHops: number): number {
  if (!request || typeof request !== "object") {
    throw invalid("route_invalid", "cross-Cell route request must be an object");
  }
  routeText(request.routeId, "routeId", L3_MAX_ROUTE_ID_BYTES);
  routeText(request.traceId, "traceId", L3_MAX_ROUTE_ID_BYTES);
  if (!isAgentIdentity(request.source) || !isAgentIdentity(request.target)) {
    throw invalid("route_invalid", "route source and target must contain four non-empty fields");
  }
  if (agentIdentityKey(request.source) === agentIdentityKey(request.target)) {
    throw invalid("route_invalid", "cross-Cell route source and target identities must differ");
  }
  if (request.source.cellId === request.target.cellId) {
    throw invalid("route_same_cell", "cross-Cell route source and target Cells must differ");
  }
  if (!request.input || typeof request.input !== "object") {
    throw invalid("route_invalid", "cross-Cell route input must be an object");
  }
  if (!isAgentIdentity(request.input.identity)
    || agentIdentityKey(request.input.identity) !== agentIdentityKey(request.target)) {
    throw invalid("route_invalid", "cross-Cell input identity must match the target identity");
  }
  if (request.input.traceId !== request.traceId) {
    throw invalid("route_invalid", "cross-Cell input traceId must match the route traceId");
  }
  const hops = request.hops === undefined
    ? 0
    : safeBoundedInteger(request.hops, "hops", 0, maxHops);
  if (hops >= maxHops) {
    throw invalid("route_hop_limit", `cross-Cell route hop limit reached at ${maxHops}`);
  }
  if (request.metadata !== undefined) {
    if (!isFiniteJson(request.metadata)) {
      throw invalid("route_invalid", "cross-Cell route metadata must be a finite JSON object");
    }
    if (new TextEncoder().encode(JSON.stringify(request.metadata)).byteLength > L3_MAX_ROUTE_METADATA_BYTES) {
      throw invalid("route_limit", "cross-Cell route metadata exceeds the configured byte bound");
    }
  }
  return hops + 1;
}

/**
 * Registry and direct forwarding boundary for independent Cells.
 *
 * Registration is O(1) by Cell ID; public summaries sort only the bounded
 * registered set. The router never returns the underlying `AgentCell`.
 */
export class CrossCellRouter {
  private readonly cells = new Map<string, AgentCell>();
  private readonly maxCells: number;
  private readonly maxHops: number;

  constructor(options: CrossCellRouterOptions = {}) {
    this.maxCells = safeBoundedInteger(
      options.maxCells ?? L3_MAX_REGISTERED_CELLS,
      "maxCells",
      1,
      L3_MAX_REGISTERED_CELLS,
    );
    this.maxHops = safeBoundedInteger(
      options.maxHops ?? L3_MAX_CROSS_CELL_HOPS,
      "maxHops",
      1,
      L3_MAX_CROSS_CELL_HOPS,
    );
  }

  /** Register one Cell; repeating the same instance is idempotent. */
  register(cellId: string, cell: AgentCell): CrossCellRegistration {
    routeText(cellId, "cellId", L3_MAX_ROUTE_ID_BYTES);
    if (!cell || typeof cell !== "object") {
      throw invalid("route_invalid", "Cell registration must provide an AgentCell");
    }
    const existing = this.cells.get(cellId);
    if (existing && existing !== cell) {
      throw invalid("route_conflict", `Cell is already registered: ${cellId}`);
    }
    if (!existing && this.cells.size >= this.maxCells) {
      throw invalid("route_limit", "registered Cell bound exceeded");
    }
    this.cells.set(cellId, cell);
    return this.registration(cellId, cell);
  }

  /** Remove one Cell registration without stopping its loops. */
  unregister(cellId: string): boolean {
    routeText(cellId, "cellId", L3_MAX_ROUTE_ID_BYTES);
    return this.cells.delete(cellId);
  }

  /** Return deterministic registration summaries without Cell handles. */
  registrations(): CrossCellRegistration[] {
    return [...this.cells.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([cellId, cell]) => this.registration(cellId, cell));
  }

  /** Forward one validated AgentInput to the target Cell. */
  async route(
    request: CrossCellRouteRequest,
    signal?: AbortSignal,
  ): Promise<CrossCellRouteReceipt> {
    const hops = validateRequest(request, this.maxHops);
    const sourceCell = this.cells.get(request.source.cellId);
    const targetCell = this.cells.get(request.target.cellId);
    if (!sourceCell || !targetCell) {
      throw invalid(
        "route_cell_not_found",
        `route Cells must be registered (source=${request.source.cellId}, target=${request.target.cellId})`,
      );
    }
    try {
      const result = await targetCell.submit(copyAgentInput(request.input), signal);
      return {
        contractVersion: L3_AGENT_CONTRACT_VERSION,
        routeId: request.routeId,
        traceId: request.traceId,
        source: copyAgentIdentity(request.source),
        target: copyAgentIdentity(request.target),
        hops,
        status: "delivered",
        result: copyRunResult(result),
        metadata: request.metadata ? copyJsonObject(request.metadata) : undefined,
      };
    } catch (error) {
      const runtimeError = error instanceof RuntimeError
        ? error
        : new RuntimeError("route_rejected", error instanceof Error ? error.message : "target Cell rejected the route");
      return rejectedReceipt(request, hops, runtimeError);
    }
  }

  /** Drain all registered Cells; registration remains until explicitly removed. */
  async drain(): Promise<void> {
    await Promise.all([...this.cells.values()].map((cell) => cell.drain()));
  }

  private registration(cellId: string, cell: AgentCell): CrossCellRegistration {
    return {
      cellId,
      loopCount: cell.snapshots().length,
    };
  }
}
