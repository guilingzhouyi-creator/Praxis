/**
 * TypeScript mirror of the Python3 protocol v1 envelope and replay cursors.
 * Python3 reference: src/l2/protocol/envelope.py — keep in sync (§2.4).
 *
 * Re-exports from types.ts (branded IDs + discriminated payloads) plus the
 * ring-buffer Outbox. Consumers import from this module as the entry point.
 */

// ── Type re-exports from types.ts ──────────────────────────────────────
export {
  PROTOCOL_VERSION, OUTBOX_MAXLEN, KINDS, CONTROL_OPS,
  asSessionId, asViewId,
} from "./types.ts";
export type {
  MessageKind, ControlOp,
  SessionId, ViewId,
  AckPayload, CommandPayload, ControlPayload,
  EventPayload, IntentPayload, ResultPayload, StreamChunkPayload,
  TypedMessage, DecodedMessage, Message,
} from "./types.ts";
export type { JsonObject, JsonValue } from "./records.ts";

import type { JsonObject } from "./records.ts";
import type { Message, MessageKind, DecodedMessage } from "./types.ts";
import { canonicalJson } from "./records.ts";
import { PROTOCOL_VERSION, OUTBOX_MAXLEN } from "./types.ts";

// ── Runtime helpers ────────────────────────────────────────────────────

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}

function nowSeconds(): number {
  return Date.now() / 1000;
}

/** Build a protocol v1 message with the same defaults as Python3. */
export function makeMessage(
  sessionId: string,
  seq: number,
  kind: MessageKind,
  payload: JsonObject,
  traceId = "",
  ts = nowSeconds(),
): Message {
  return { v: PROTOCOL_VERSION, session_id: sessionId, seq, ts, trace_id: traceId, kind, payload };
}

// ── Payload validation ─────────────────────────────────────────────────

const CONTROL_OPS_SET = new Set<string>(["attach", "detach", "resume", "recovery", "ack"]);

function validatePayload(kind: MessageKind, payload: JsonObject): string[] {
  const errors: string[] = [];
  if (kind === "command") {
    if (typeof payload.name !== "string" || payload.name.length === 0)
      errors.push("command payload requires a non-empty name");
    if (payload.args !== undefined && (!Array.isArray(payload.args) || payload.args.some((arg) => typeof arg !== "string")))
      errors.push("command payload args must be a string array");
  } else if (kind === "intent") {
    if (typeof payload.text !== "string" || payload.text.length === 0)
      errors.push("intent payload requires non-empty text");
  } else if (kind === "result") {
    if (typeof payload.success !== "boolean")
      errors.push("result payload requires boolean success");
  } else if (kind === "stream_chunk") {
    if (typeof payload.data !== "string")
      errors.push("stream_chunk payload requires string data");
  } else if (kind === "control") {
    const op = payload.op;
    if (typeof op !== "string" || !CONTROL_OPS_SET.has(op))
      errors.push(`control payload has unknown op: ${String(op)}`);
    if (payload.session_id !== undefined && (typeof payload.session_id !== "string" || (payload.session_id as string).length === 0))
      errors.push("control payload session_id must be a non-empty string");
    if (payload.last_acked !== undefined && !isInteger(payload.last_acked, -1))
      errors.push("control payload last_acked must be an integer >= -1");
  } else if (kind === "ack" && !isInteger(payload.ack_seq)) {
    errors.push("ack payload requires a non-negative integer ack_seq");
  }
  return errors;
}

// ── Envelope validation ────────────────────────────────────────────────

const REQUIRED_FIELDS = new Set(["v", "session_id", "seq", "ts", "kind", "payload"]);
const KINDS_SET = new Set<string>(["ack", "command", "control", "event", "intent", "result", "stream_chunk"]);

export function validateMessage(message: unknown): string[] {
  /** Return validation errors; empty = valid. */
  if (!isObject(message)) return ["envelope must be an object"];
  const rec = message as Record<string, unknown>;
  const errors: string[] = [];
  for (const field of REQUIRED_FIELDS) {
    if (!(field in rec)) errors.push(`missing field: ${field}`);
  }
  if (errors.length > 0) return errors;
  if (rec.v !== PROTOCOL_VERSION) errors.push(`unsupported version: ${String(rec.v)}`);
  if (typeof rec.session_id !== "string" || rec.session_id.length === 0)
    errors.push("session_id must be a non-empty string");
  if (!isInteger(rec.seq)) errors.push("seq must be a non-negative integer");
  if (typeof rec.kind !== "string" || !KINDS_SET.has(rec.kind))
    errors.push(`unknown kind: ${String(rec.kind)}`);
  if (typeof rec.ts !== "number" || !Number.isFinite(rec.ts))
    errors.push("ts must be a number");
  if ("trace_id" in rec && typeof rec.trace_id !== "string")
    errors.push("trace_id must be a string");
  if (!isObject(rec.payload)) {
    errors.push("payload must be an object");
  } else if (typeof rec.kind === "string" && KINDS_SET.has(rec.kind)) {
    errors.push(...validatePayload(rec.kind as MessageKind, rec.payload));
  }
  return errors;
}

export function encodeMessage(message: Message): string {
  /** Serialize a valid envelope with recursively sorted keys. */
  const errors = validateMessage(message);
  if (errors.length > 0) throw new Error(errors.join("; "));
  return canonicalJson(message);
}

export function decodeMessage(line: string): DecodedMessage {
  /** Decode and validate one JSONL envelope without throwing parse errors. */
  if (typeof line !== "string" || line.trim().length === 0) return { message: null, error: "empty line" };
  let raw: unknown;
  try {
    raw = JSON.parse(line);
  } catch (error) {
    return { message: null, error: `invalid json: ${String(error)}` };
  }
  const errors = validateMessage(raw);
  if (errors.length > 0) return { message: null, error: errors.join("; ") };
  return { message: raw as Message, error: null };
}

// ── Outbox (ring buffer, O(1) append vs O(n) shift) ────────────────────

/**
 * Bounded per-session replay window backed by a circular buffer.
 *
 * The naive `Array.shift()` eviction is O(n); this ring buffer tracks a
 * logical head index for O(1) amortised append. Non-destructive ack
 * semantics mirror the Python3 host exactly.
 */
export class Outbox {
  private buf: (Message | undefined)[];
  private head = 0;
  private count = 0;
  private acknowledged = -1;

  constructor(public readonly maxlen = OUTBOX_MAXLEN) {
    if (!Number.isInteger(maxlen) || maxlen < 1) throw new Error("maxlen must be a positive integer");
    this.buf = new Array(maxlen);
  }

  append(message: Message): void {
    if (this.count < this.maxlen) {
      this.buf[(this.head + this.count) % this.maxlen] = message;
      this.count++;
    } else {
      // Overwrite oldest slot.
      this.buf[this.head] = message;
      this.head = (this.head + 1) % this.maxlen;
    }
  }

  /** Non-destructive ack: only the cursor advances; items remain for lagging views. */
  ack(seq: number): void {
    this.acknowledged = Math.max(this.acknowledged, seq);
  }

  /** Replay window for one view cursor (messages after afterSeq), oldest-first. */
  unacked(afterSeq?: number): Message[] {
    const after = afterSeq ?? this.acknowledged;
    const result: Message[] = [];
    for (let i = 0; i < this.count; i++) {
      const msg = this.buf[(this.head + i) % this.buf.length];
      if (msg && msg.seq > after) result.push(msg);
    }
    return result;
  }

  get lastAcked(): number {
    return this.acknowledged;
  }

  get size(): number {
    return this.count;
  }
}

// ── SessionCursor (per-view ack cursor) ────────────────────────────────

export class SessionCursor {
  sessionId = "";
  lastAcked = -1;
  attached = false;

  constructor(public readonly viewId: string) {}

  attach(sessionId: string): void {
    this.sessionId = sessionId;
    this.attached = true;
  }

  detach(): void {
    this.attached = false;
  }

  ack(seq: number): void {
    this.lastAcked = Math.max(this.lastAcked, seq);
  }
}
