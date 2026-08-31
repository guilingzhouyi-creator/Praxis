/**
 * Bounded, tamper-evident evidence projection for the TypeScript L3 rewrite.
 *
 * This is an in-memory side channel. It provides deterministic chain/query/
 * verification values for tests and host adapters; it does not persist files,
 * execute commands, or become the Rust gate/constitution authority.
 */

import { createHash } from "node:crypto";
import type {
  AgentIdentity,
  AgentRuntimeEvent,
} from "../contracts/agent-contracts.ts";
import type { JsonObject, JsonValue } from "../../protocol/wire-records.ts";
import {
  L3_GOVERNANCE_HASH_PREFIX_LENGTH,
  L3_GOVERNANCE_MAX_EVIDENCE_CHAINS,
  L3_GOVERNANCE_MAX_EVIDENCE_LABEL_BYTES,
  L3_GOVERNANCE_MAX_EVIDENCE_POINTS,
  L3_GOVERNANCE_MAX_EVIDENCE_RAW_BYTES,
} from "./governance-limits.ts";

/** Stable decision vocabulary shared by governance projections. */
export type EvidenceDecision =
  | "CHANGE"
  | "ALLOW"
  | "BYPASS"
  | "BLOCK"
  | "WARN"
  | "FULL_POWER"
  | "AUTO_APPROVED";

/** Input accepted by the evidence ledger. */
export interface EvidenceInput {
  readonly phase: string;
  readonly gate?: string;
  readonly decision?: EvidenceDecision;
  readonly target?: string;
  readonly source?: string;
  readonly tags?: Readonly<Record<string, string>>;
  readonly raw?: JsonObject;
  readonly chainKind?: string;
}

/** Detached evidence point with a row-fixity hash. */
export interface EvidencePoint {
  readonly evidenceId: string;
  readonly chainId: string;
  readonly sequence: number;
  readonly ts: number;
  readonly phase: string;
  readonly gate: string;
  readonly decision: EvidenceDecision;
  readonly target: string;
  readonly source: string;
  readonly tags: Readonly<Record<string, string>>;
  readonly raw: JsonObject;
  readonly rawSize: number;
  readonly rawHash: string;
  readonly prevHash: string;
  readonly hashPrefix: string;
}

/** Detached chain summary. */
export interface EvidenceChain {
  readonly chainId: string;
  readonly kind: string;
  readonly source: string;
  readonly opened: number;
  readonly closed: number | null;
  readonly reason: string;
  readonly evidenceCount: number;
}

/** Query filters for evidence points. */
export interface EvidenceQuery {
  readonly chainId?: string;
  readonly phase?: string;
  readonly decision?: EvidenceDecision;
  readonly target?: string;
  readonly limit?: number;
}

/** Result of checking the retained hash chain. */
export interface EvidenceVerification {
  readonly valid: boolean;
  readonly checked: number;
  readonly error?: string;
  readonly evidenceId?: string;
}

/** Versioned durable document exchanged with a storage adapter. */
export const EVIDENCE_LEDGER_DOCUMENT_VERSION = 1 as const;

/** Complete bounded ledger state required for crash/restart recovery. */
export interface EvidenceLedgerDocument {
  readonly version: typeof EVIDENCE_LEDGER_DOCUMENT_VERSION;
  readonly sequence: number;
  readonly chainSequence: number;
  readonly lastHash: string;
  readonly baseHash: string;
  readonly points: readonly EvidencePoint[];
  readonly chains: readonly EvidenceChain[];
}

/** Read-only ledger contract that host adapters can replace with durability. */
export interface EvidencePort {
  record(input: EvidenceInput): string;
  beginChain(kind: string, source?: string): string;
  closeChain(chainId: string, reason?: string): EvidenceChain | null;
  query(filter?: EvidenceQuery): readonly EvidencePoint[];
  chains(limit?: number): readonly EvidenceChain[];
  verify(): EvidenceVerification;
}

interface MutableChain {
  readonly chainId: string;
  readonly kind: string;
  readonly source: string;
  readonly opened: number;
  closed: number | null;
  reason: string;
  evidenceCount: number;
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function boundedLabel(value: unknown): string {
  const text = String(value ?? "");
  if (utf8Bytes(text) <= L3_GOVERNANCE_MAX_EVIDENCE_LABEL_BYTES) return text;
  const bytes = new TextEncoder().encode(text).slice(0, L3_GOVERNANCE_MAX_EVIDENCE_LABEL_BYTES);
  return new TextDecoder().decode(bytes);
}

function isJsonValue(value: unknown, ancestors: WeakSet<object> = new WeakSet<object>()): value is JsonValue {
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

function cloneJsonValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map((item) => cloneJsonValue(item));
  if (value !== null && typeof value === "object") {
    const result: JsonObject = {};
    for (const [key, item] of Object.entries(value)) result[key] = cloneJsonValue(item);
    return result;
  }
  return value;
}

function cloneJsonObject(value: JsonObject): JsonObject {
  return cloneJsonValue(value) as JsonObject;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  const object = value as Record<string, unknown>;
  const fields = Object.keys(object)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`)
    .join(",");
  return `{${fields}}`;
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function boundedRaw(raw: JsonObject | undefined): { readonly value: JsonObject; readonly size: number } {
  const source = raw ?? {};
  if (!isJsonValue(source)) throw new TypeError("evidence raw must be a finite JSON object");
  const detached = cloneJsonObject(source);
  const encoded = canonicalJson(detached);
  const size = utf8Bytes(encoded);
  if (size <= L3_GOVERNANCE_MAX_EVIDENCE_RAW_BYTES) return { value: detached, size };
  const snapshot = encoded.slice(0, L3_GOVERNANCE_MAX_EVIDENCE_RAW_BYTES);
  return {
    value: { truncated: true, snapshot: `${snapshot}...` },
    size,
  };
}

function identityTags(identity: AgentIdentity): Readonly<Record<string, string>> {
  return {
    agent_id: boundedLabel(identity.agentId),
    cell_id: boundedLabel(identity.cellId),
    session_id: boundedLabel(identity.sessionId),
    terminal_id: boundedLabel(identity.terminalId),
  };
}

function rowFields(point: EvidencePoint): Record<string, unknown> {
  return {
    evidence_id: point.evidenceId,
    chain_id: point.chainId,
    sequence: point.sequence,
    ts: point.ts,
    phase: point.phase,
    gate: point.gate,
    decision: point.decision,
    target: point.target,
    source: point.source,
    tags: point.tags,
    raw: point.raw,
    raw_size: point.rawSize,
    raw_hash: point.rawHash,
    prev_hash: point.prevHash,
  };
}

function requirePositiveLimit(value: number, name: string, maximum = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new TypeError(`${name} must be a safe integer between 1 and ${maximum}`);
  }
  return value;
}

/** Bounded in-memory evidence ledger with append-only row hashes. */
export class InMemoryEvidenceLedger implements EvidencePort {
  private readonly maxPoints: number;
  private readonly maxChains: number;
  private readonly clock: () => number;
  private readonly points: EvidencePoint[] = [];
  private readonly chainMap = new Map<string, MutableChain>();
  private readonly openKinds = new Map<string, string>();
  private sequence = 0;
  private chainSequence = 0;
  private lastHash = "";
  private baseHash = "";

  constructor(options: {
    readonly maxPoints?: number;
    readonly maxChains?: number;
    readonly clock?: () => number;
  } = {}) {
    this.maxPoints = requirePositiveLimit(
      options.maxPoints ?? L3_GOVERNANCE_MAX_EVIDENCE_POINTS,
      "maxPoints",
    );
    this.maxChains = requirePositiveLimit(
      options.maxChains ?? L3_GOVERNANCE_MAX_EVIDENCE_CHAINS,
      "maxChains",
    );
    this.clock = options.clock ?? (() => Date.now() / 1000);
  }

  /** Open or reuse one chain kind. */
  beginChain(kind: string, source = ""): string {
    const normalizedKind = boundedLabel(kind || "ambient");
    const existing = this.openKinds.get(normalizedKind);
    if (existing) return existing;
    this.chainSequence += 1;
    const chainId = `ch_${this.chainSequence.toString(16).padStart(L3_GOVERNANCE_HASH_PREFIX_LENGTH, "0")}`;
    this.chainMap.set(chainId, {
      chainId,
      kind: normalizedKind,
      source: boundedLabel(source),
      opened: this.clock(),
      closed: null,
      reason: "",
      evidenceCount: 0,
    });
    this.openKinds.set(normalizedKind, chainId);
    this.pruneChains();
    return chainId;
  }

  /** Append one bounded evidence point and return its chain id. */
  record(input: EvidenceInput): string {
    if (!input || typeof input !== "object" || !input.phase) {
      throw new TypeError("evidence phase is required");
    }
    const chainKind = boundedLabel(input.chainKind || "ambient");
    const chainId = this.beginChain(chainKind, input.source);
    const chain = this.chainMap.get(chainId);
    if (!chain) throw new Error(`evidence chain disappeared: ${chainId}`);
    this.sequence += 1;
    const evidenceId = `ev_${this.sequence.toString(16).padStart(L3_GOVERNANCE_HASH_PREFIX_LENGTH, "0")}`;
    const raw = boundedRaw(input.raw);
    const rawCanonical = canonicalJson(input.raw ?? {});
    const point: EvidencePoint = {
      evidenceId,
      chainId,
      sequence: this.sequence,
      ts: this.clock(),
      phase: boundedLabel(input.phase),
      gate: boundedLabel(input.gate || input.phase),
      decision: input.decision ?? "ALLOW",
      target: boundedLabel(input.target),
      source: boundedLabel(input.source),
      tags: Object.fromEntries(
        Object.entries(input.tags ?? {}).map(([key, value]) => [boundedLabel(key), boundedLabel(value)]),
      ),
      raw: raw.value,
      rawSize: raw.size,
      rawHash: sha256(rawCanonical),
      prevHash: this.lastHash,
      hashPrefix: "",
    };
    const hash = sha256(canonicalJson(rowFields(point)));
    const detached = { ...point, hashPrefix: hash.slice(0, L3_GOVERNANCE_HASH_PREFIX_LENGTH) };
    this.points.push(detached);
    this.lastHash = hash;
    chain.evidenceCount += 1;
    if (this.points.length > this.maxPoints) {
      const evicted = this.points.shift();
      if (evicted) this.baseHash = this.hashFor(evicted);
    }
    return chainId;
  }

  /** Close one chain idempotently and return its detached summary. */
  closeChain(chainId: string, reason = ""): EvidenceChain | null {
    const chain = this.chainMap.get(chainId);
    if (!chain) return null;
    if (chain.closed === null) {
      chain.closed = this.clock();
      chain.reason = boundedLabel(reason);
      if (this.openKinds.get(chain.kind) === chainId) this.openKinds.delete(chain.kind);
    }
    return this.toChain(chain);
  }

  /** Return newest-first detached points matching optional filters. */
  query(filter: EvidenceQuery = {}): readonly EvidencePoint[] {
    const limit = filter.limit === undefined
      ? this.maxPoints
      : requirePositiveLimit(filter.limit, "limit", this.maxPoints);
    return this.points
      .filter((point) => (
        (!filter.chainId || point.chainId === filter.chainId)
        && (!filter.phase || point.phase === filter.phase)
        && (!filter.decision || point.decision === filter.decision)
        && (!filter.target || point.target === filter.target)
      ))
      .slice(-limit)
      .reverse()
      .map((point) => this.clonePoint(point));
  }

  /** Return newest-first detached chain summaries. */
  chains(limit = this.maxChains): readonly EvidenceChain[] {
    const bounded = requirePositiveLimit(limit, "limit", this.maxChains);
    return [...this.chainMap.values()]
      .sort((left, right) => right.opened - left.opened)
      .slice(0, bounded)
      .map((chain) => this.toChain(chain));
  }

  /** Verify retained row fixity and predecessor links. */
  verify(): EvidenceVerification {
    let previous = this.baseHash;
    let checked = 0;
    for (const point of this.points) {
      if (point.prevHash !== previous) {
        return {
          valid: false,
          checked,
          evidenceId: point.evidenceId,
          error: `previous hash mismatch at ${point.evidenceId}`,
        };
      }
      const expected = this.hashFor(point);
      const prefix = expected.slice(0, L3_GOVERNANCE_HASH_PREFIX_LENGTH);
      if (prefix !== point.hashPrefix) {
        return {
          valid: false,
          checked,
          evidenceId: point.evidenceId,
          error: `row hash mismatch at ${point.evidenceId}`,
        };
      }
      previous = expected;
      checked += 1;
    }
    return { valid: true, checked };
  }

  /** Record only bounded metadata from one runtime lifecycle event. */
  recordRuntimeEvent(event: AgentRuntimeEvent): string | null {
    if (
      event.type !== "run_failed"
      && event.type !== "kernel_request_completed"
      && event.type !== "tool_result_completed"
    ) {
      return null;
    }
    const blocked = event.type === "run_failed"
      || event.data.accepted === false
      || event.data.success === false;
    return this.record({
      phase: "l3_runtime",
      gate: event.type,
      decision: blocked ? "BLOCK" : "ALLOW",
      target: event.type,
      source: "ts-l3-runtime",
      tags: identityTags(event.identity),
      raw: {
        event_seq: event.eventSeq,
        run_id: event.runId,
        trace_id: event.traceId,
        type: event.type,
      },
      chainKind: blocked ? "runtime-block" : "ambient",
    });
  }

  /** Return the latest retained sequence/hash metadata. */
  snapshot(): {
    readonly retainedPoints: number;
    readonly chains: number;
    readonly nextSequence: number;
    readonly lastHashPrefix: string | null;
    readonly verification: EvidenceVerification;
  } {
    return {
      retainedPoints: this.points.length,
      chains: this.chainMap.size,
      nextSequence: this.sequence + 1,
      lastHashPrefix: this.lastHash ? this.lastHash.slice(0, L3_GOVERNANCE_HASH_PREFIX_LENGTH) : null,
      verification: this.verify(),
    };
  }

  /** Export a detached, versioned document for a durable adapter. */
  exportDocument(): EvidenceLedgerDocument {
    return {
      version: EVIDENCE_LEDGER_DOCUMENT_VERSION,
      sequence: this.sequence,
      chainSequence: this.chainSequence,
      lastHash: this.lastHash,
      baseHash: this.baseHash,
      points: this.points.map((point) => this.clonePoint(point)),
      chains: [...this.chainMap.values()].map((chain) => this.toChain(chain)),
    };
  }

  /** Restore a validated document after a crash/restart or transaction rollback. */
  importDocument(document: EvidenceLedgerDocument): void {
    this.validateDocument(document);
    this.points.length = 0;
    this.chainMap.clear();
    this.openKinds.clear();
    this.sequence = document.sequence;
    this.chainSequence = document.chainSequence;
    this.lastHash = document.lastHash;
    this.baseHash = document.baseHash;
    for (const point of document.points) this.points.push(this.clonePoint(point));
    for (const chain of document.chains) {
      this.chainMap.set(chain.chainId, {
        ...chain,
      });
      if (chain.closed === null) this.openKinds.set(chain.kind, chain.chainId);
    }
  }

  private hashFor(point: EvidencePoint): string {
    return sha256(canonicalJson(rowFields(point)));
  }

  private clonePoint(point: EvidencePoint): EvidencePoint {
    return {
      ...point,
      tags: { ...point.tags },
      raw: cloneJsonObject(point.raw),
    };
  }

  private toChain(chain: MutableChain): EvidenceChain {
    return {
      chainId: chain.chainId,
      kind: chain.kind,
      source: chain.source,
      opened: chain.opened,
      closed: chain.closed,
      reason: chain.reason,
      evidenceCount: chain.evidenceCount,
    };
  }

  private validateDocument(document: EvidenceLedgerDocument): void {
    if (!document || document.version !== EVIDENCE_LEDGER_DOCUMENT_VERSION) {
      throw new TypeError("unsupported evidence ledger document version");
    }
    if (
      !Number.isSafeInteger(document.sequence)
      || document.sequence < 0
      || !Number.isSafeInteger(document.chainSequence)
      || document.chainSequence < 0
    ) {
      throw new TypeError("evidence ledger sequence values must be non-negative safe integers");
    }
    if (!Array.isArray(document.points) || document.points.length > this.maxPoints) {
      throw new TypeError("evidence ledger points exceed the configured bound");
    }
    if (!Array.isArray(document.chains) || document.chains.length > this.maxChains) {
      throw new TypeError("evidence ledger chains exceed the configured bound");
    }
    const chains = new Map(document.chains.map((chain) => [chain.chainId, chain]));
    let previous = document.baseHash;
    let lastSequence = 0;
    for (const point of document.points) {
      if (
        !point
        || !Number.isSafeInteger(point.sequence)
        || point.sequence <= lastSequence
        || point.sequence > document.sequence
        || !chains.has(point.chainId)
      ) {
        throw new TypeError(`invalid evidence point sequence or chain: ${point?.evidenceId ?? "unknown"}`);
      }
      if (point.prevHash !== previous) {
        throw new TypeError(`evidence predecessor mismatch at ${point.evidenceId}`);
      }
      const expected = this.hashFor(point);
      if (expected.slice(0, L3_GOVERNANCE_HASH_PREFIX_LENGTH) !== point.hashPrefix) {
        throw new TypeError(`evidence row hash mismatch at ${point.evidenceId}`);
      }
      if (sha256(canonicalJson(point.raw)) !== point.rawHash && point.rawSize <= L3_GOVERNANCE_MAX_EVIDENCE_RAW_BYTES) {
        throw new TypeError(`evidence raw hash mismatch at ${point.evidenceId}`);
      }
      previous = expected;
      lastSequence = point.sequence;
    }
    if (document.points.length > 0 && document.lastHash !== previous) {
      throw new TypeError("evidence ledger last hash does not match retained points");
    }
    if (document.points.length === 0 && document.lastHash !== document.baseHash) {
      throw new TypeError("empty evidence ledger must use base hash as last hash");
    }
    for (const chain of document.chains) {
      if (
        !chain
        || !chain.chainId
        || !chain.kind
        || !Number.isFinite(chain.opened)
        || (chain.closed !== null && !Number.isFinite(chain.closed))
        || !Number.isSafeInteger(chain.evidenceCount)
        || chain.evidenceCount < 0
      ) {
        throw new TypeError("invalid evidence chain summary");
      }
    }
  }

  private pruneChains(): void {
    if (this.chainMap.size <= this.maxChains) return;
    const candidates = [...this.chainMap.values()]
      .sort((left, right) => left.opened - right.opened);
    while (this.chainMap.size > this.maxChains) {
      const oldest = candidates.shift();
      if (!oldest) break;
      this.chainMap.delete(oldest.chainId);
      if (this.openKinds.get(oldest.kind) === oldest.chainId) this.openKinds.delete(oldest.kind);
    }
  }
}
