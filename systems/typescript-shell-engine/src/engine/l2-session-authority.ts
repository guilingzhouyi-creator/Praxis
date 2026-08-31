/**
 * Authoritative TypeScript L2 session data boundary.
 *
 * This module owns only protocol-v1 output sequencing, bounded session replay,
 * and per-frontend cursors. It does not own AgentLoop state, provider work,
 * transport handles, processes, terminals, or Rust policy. L3 injects this
 * boundary through `L2SessionProjection`.
 */

import type { Message } from "../protocol/wire-envelope.ts";
import {
  OUTBOX_MAXLEN,
  Outbox,
  SessionCursor,
  validateMessage,
} from "../protocol/wire-envelope.ts";
import { MAX_SAFE_SEQUENCE } from "../protocol/wire-types.ts";
import type { JsonObject, JsonValue } from "../protocol/wire-records.ts";
import { canonicalJson } from "../protocol/wire-records.ts";

/** Default bound on independently tracked L2 sessions in one host. */
export const DEFAULT_L2_AUTHORITY_MAX_SESSIONS = 256 as const;

/** Sink for protocol-v1 messages owned by the L2 session host. */
export interface L2MessageSink {
  publish(message: Message): void | Promise<void>;
}

/** Session sequence authority used by L2 projections. */
export interface L2SessionSequencePort {
  next(sessionId: string): number;
}

/** Options for the bounded L2 session authority. */
export interface L2SessionAuthorityOptions {
  readonly maxSessions?: number;
  readonly outboxMaxlen?: number;
}

/** Detached summary of one L2 frontend cursor. */
export interface L2SessionViewSnapshot {
  readonly viewId: string;
  readonly sessionId: string;
  readonly lastAcked: number;
  readonly attached: boolean;
}

/** Detached summary of one L2 session authority record. */
export interface L2SessionAuthoritySnapshot {
  readonly sessionId: string;
  readonly nextSequence: number;
  readonly nextCommittedSequence: number;
  readonly retainedMessages: number;
  readonly oldestSequence: number | null;
  readonly latestSequence: number | null;
  readonly pendingMessages: number;
  readonly views: readonly L2SessionViewSnapshot[];
}

/** Machine-readable failures raised at the L2 authority boundary. */
export type L2SessionAuthorityErrorCode =
  | "invalid_session"
  | "session_limit"
  | "sequence_exhausted"
  | "message_invalid"
  | "sequence_unreserved"
  | "sequence_gap"
  | "message_conflict"
  | "message_stale"
  | "view_not_attached";

/** Fail-closed L2 session authority error. */
export class L2SessionAuthorityError extends Error {
  /** Machine-readable authority failure category. */
  readonly code: L2SessionAuthorityErrorCode;

  constructor(code: L2SessionAuthorityErrorCode, message: string) {
    super(message);
    this.name = "L2SessionAuthorityError";
    this.code = code;
  }
}

interface SessionRecord {
  readonly sessionId: string;
  readonly outbox: Outbox;
  readonly views: Map<string, SessionCursor>;
  readonly pending: Map<number, Message>;
  nextSequence: number;
  nextCommittedSequence: number;
}

function requireSessionId(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw new L2SessionAuthorityError("invalid_session", "sessionId must be a non-empty string without NUL");
  }
}

function requireViewId(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw new L2SessionAuthorityError("invalid_session", "viewId must be a non-empty string without NUL");
  }
}

function requireSequence(value: unknown, name: string, minimum = 1): asserts value is number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > MAX_SAFE_SEQUENCE) {
    throw new L2SessionAuthorityError(
      "message_invalid",
      `${name} must be a safe integer between ${minimum} and ${MAX_SAFE_SEQUENCE}`,
    );
  }
}

function copyJsonValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map((item) => copyJsonValue(item));
  if (value !== null && typeof value === "object") {
    const result: JsonObject = {};
    for (const [key, item] of Object.entries(value)) result[key] = copyJsonValue(item);
    return result;
  }
  return value;
}

function copyMessage(message: Message): Message {
  return {
    ...message,
    payload: copyJsonValue(message.payload) as JsonObject,
  };
}

function sameMessage(left: Message, right: Message): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

function validateAuthorityOptions(options: L2SessionAuthorityOptions): {
  maxSessions: number;
  outboxMaxlen: number;
} {
  const maxSessions = options.maxSessions ?? DEFAULT_L2_AUTHORITY_MAX_SESSIONS;
  const outboxMaxlen = options.outboxMaxlen ?? OUTBOX_MAXLEN;
  if (!Number.isSafeInteger(maxSessions) || maxSessions < 1) {
    throw new TypeError("maxSessions must be a positive safe integer");
  }
  if (!Number.isSafeInteger(outboxMaxlen) || outboxMaxlen < 1) {
    throw new TypeError("outboxMaxlen must be a positive safe integer");
  }
  return { maxSessions, outboxMaxlen };
}

/**
 * Bounded L2 host authority for output messages and frontend cursors.
 *
 * Sequence allocation is reservation-based because the projection builds a
 * message before publishing it. Publications are committed only when all
 * lower reserved sequences have arrived, so concurrent L3 identities cannot
 * expose a replay gap. A permanently unsubmitted reservation remains visible
 * as `pendingMessages` instead of being silently skipped.
 */
export class L2SessionAuthority implements L2SessionSequencePort, L2MessageSink {
  private readonly sessions = new Map<string, SessionRecord>();
  private readonly maxSessions: number;
  private readonly outboxMaxlen: number;

  constructor(options: L2SessionAuthorityOptions = {}) {
    const resolved = validateAuthorityOptions(options);
    this.maxSessions = resolved.maxSessions;
    this.outboxMaxlen = resolved.outboxMaxlen;
  }

  /** Reserve the next protocol-v1 output sequence for one session. */
  next(sessionId: string): number {
    const record = this.getOrCreate(sessionId);
    if (record.nextSequence >= MAX_SAFE_SEQUENCE) {
      throw new L2SessionAuthorityError("sequence_exhausted", "session output sequence exhausted");
    }
    const sequence = record.nextSequence;
    record.nextSequence += 1;
    return sequence;
  }

  /**
   * Commit one projected message into the authoritative bounded replay window.
   *
   * Messages may arrive out of order from concurrent L3 identities, but are
   * made visible only after the contiguous prefix can be flushed.
   */
  publish(message: Message): void {
    const errors = validateMessage(message);
    if (errors.length > 0) {
      throw new L2SessionAuthorityError("message_invalid", `invalid L2 message: ${errors.join("; ")}`);
    }
    requireSessionId(message.session_id);
    requireSequence(message.seq, "message sequence");
    const record = this.getOrCreate(message.session_id);
    if (message.seq >= record.nextSequence) {
      throw new L2SessionAuthorityError(
        "sequence_unreserved",
        `message sequence ${message.seq} was not reserved for session ${message.session_id}`,
      );
    }
    if (message.seq < record.nextCommittedSequence) {
      const existing = this.retained(record).find((candidate) => candidate.seq === message.seq);
      if (existing && sameMessage(existing, message)) return;
      throw new L2SessionAuthorityError(
        "message_stale",
        `message sequence ${message.seq} is already committed or evicted`,
      );
    }
    const pending = record.pending.get(message.seq);
    if (pending) {
      if (sameMessage(pending, message)) return;
      throw new L2SessionAuthorityError("message_conflict", `conflicting message for sequence ${message.seq}`);
    }
    record.pending.set(message.seq, copyMessage(message));
    this.flush(record);
  }

  /** Attach one frontend view to a session; attachment is idempotent. */
  attach(sessionId: string, viewId: string): L2SessionViewSnapshot {
    requireViewId(viewId);
    const record = this.getOrCreate(sessionId);
    let cursor = record.views.get(viewId);
    if (!cursor) {
      cursor = new SessionCursor(viewId);
      record.views.set(viewId, cursor);
    }
    if (cursor.attached && cursor.sessionId !== sessionId) {
      throw new L2SessionAuthorityError("view_not_attached", `view ${viewId} is bound to another session`);
    }
    cursor.attach(sessionId);
    return this.viewSnapshot(cursor);
  }

  /** Detach one frontend view while retaining its monotonic cursor. */
  detach(sessionId: string, viewId: string): boolean {
    const record = this.get(sessionId);
    if (!record) return false;
    requireViewId(viewId);
    const cursor = record.views.get(viewId);
    if (!cursor) return false;
    cursor.detach();
    return true;
  }

  /** Advance one attached frontend cursor without deleting retained messages. */
  ack(sessionId: string, viewId: string, ackSequence: number): void {
    const cursor = this.requireAttachedCursor(sessionId, viewId);
    requireSequence(ackSequence, "ack sequence", 0);
    cursor.ack(ackSequence);
  }

  /** Replay messages after a view cursor or an explicit detached cursor. */
  replay(sessionId: string, viewId?: string, afterSequence?: number): Message[] {
    const record = this.get(sessionId);
    if (!record) return [];
    let after = afterSequence ?? -1;
    if (viewId !== undefined) {
      const cursor = this.requireAttachedCursor(sessionId, viewId);
      after = afterSequence ?? cursor.lastAcked;
    }
    requireSequence(after, "replay cursor", -1);
    return this.retained(record)
      .filter((message) => message.seq > after)
      .map((message) => copyMessage(message));
  }

  /** Return one detached authority summary, or null when unseen. */
  snapshot(sessionId: string): L2SessionAuthoritySnapshot | null {
    const record = this.get(sessionId);
    return record ? this.snapshotRecord(record) : null;
  }

  /** Return deterministic summaries for every tracked session. */
  snapshots(): L2SessionAuthoritySnapshot[] {
    return [...this.sessions.values()]
      .sort((left, right) => left.sessionId.localeCompare(right.sessionId))
      .map((record) => this.snapshotRecord(record));
  }

  /** Drop one volatile session record; no durable state is affected. */
  clear(sessionId: string): boolean {
    requireSessionId(sessionId);
    return this.sessions.delete(sessionId);
  }

  private getOrCreate(sessionId: string): SessionRecord {
    requireSessionId(sessionId);
    const existing = this.sessions.get(sessionId);
    if (existing) return existing;
    if (this.sessions.size >= this.maxSessions) {
      throw new L2SessionAuthorityError("session_limit", "L2 session authority bound exceeded");
    }
    const record: SessionRecord = {
      sessionId,
      outbox: new Outbox(this.outboxMaxlen),
      views: new Map(),
      pending: new Map(),
      nextSequence: 1,
      nextCommittedSequence: 1,
    };
    this.sessions.set(sessionId, record);
    return record;
  }

  private get(sessionId: string): SessionRecord | null {
    requireSessionId(sessionId);
    return this.sessions.get(sessionId) ?? null;
  }

  private requireAttachedCursor(sessionId: string, viewId: string): SessionCursor {
    requireViewId(viewId);
    const record = this.get(sessionId);
    const cursor = record?.views.get(viewId);
    if (!cursor || !cursor.attached || cursor.sessionId !== sessionId) {
      throw new L2SessionAuthorityError("view_not_attached", `view ${viewId} is not attached to ${sessionId}`);
    }
    return cursor;
  }

  private retained(record: SessionRecord): Message[] {
    return record.outbox
      .unacked(-1)
      .sort((left, right) => left.seq - right.seq);
  }

  private flush(record: SessionRecord): void {
    while (record.pending.has(record.nextCommittedSequence)) {
      const message = record.pending.get(record.nextCommittedSequence)!;
      record.pending.delete(record.nextCommittedSequence);
      record.outbox.append(message);
      record.nextCommittedSequence += 1;
    }
  }

  private viewSnapshot(cursor: SessionCursor): L2SessionViewSnapshot {
    return {
      viewId: cursor.viewId,
      sessionId: cursor.sessionId,
      lastAcked: cursor.lastAcked,
      attached: cursor.attached,
    };
  }

  private snapshotRecord(record: SessionRecord): L2SessionAuthoritySnapshot {
    const retained = this.retained(record);
    return {
      sessionId: record.sessionId,
      nextSequence: record.nextSequence,
      nextCommittedSequence: record.nextCommittedSequence,
      retainedMessages: retained.length,
      oldestSequence: retained[0]?.seq ?? null,
      latestSequence: retained[retained.length - 1]?.seq ?? null,
      pendingMessages: record.pending.size,
      views: [...record.views.values()]
        .sort((left, right) => left.viewId.localeCompare(right.viewId))
        .map((cursor) => this.viewSnapshot(cursor)),
    };
  }
}
