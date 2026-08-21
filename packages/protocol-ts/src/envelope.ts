/**
 * TypeScript mirror of the Python protocol v1 envelope and replay cursors.
 * Python reference (single source of truth): src/l2/protocol/envelope.py —
 * keep fields, kinds and the non-destructive ack semantics in sync (§2.4).
 */

import { canonicalJson, JsonObject } from "./records.ts";

export const PROTOCOL_VERSION = 1 as const;
export const OUTBOX_MAXLEN = 1024;
export const KINDS = ["ack", "command", "control", "event", "intent", "result", "stream_chunk"] as const;
export type MessageKind = (typeof KINDS)[number];

export const CONTROL_KINDS = ["attach", "detach", "resume", "recovery", "ack"] as const;
export type ControlKind = (typeof CONTROL_KINDS)[number];

export interface Message {
  v: typeof PROTOCOL_VERSION;
  session_id: string;
  seq: number;
  ts: number;
  trace_id?: string;
  kind: MessageKind;
  payload: JsonObject;
}

export interface DecodedMessage {
  message: Message | null;
  error: string | null;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}

function nowSeconds(): number {
  return Date.now() / 1000;
}

export function makeMessage(
  sessionId: string,
  seq: number,
  kind: MessageKind,
  payload: JsonObject,
  traceId = "",
  ts = nowSeconds(),
): Message {
  /** Build a protocol v1 message with the same defaults as Python. */
  return { v: PROTOCOL_VERSION, session_id: sessionId, seq, ts, trace_id: traceId, kind, payload };
}

function validatePayload(kind: MessageKind, payload: JsonObject): string[] {
  const errors: string[] = [];
  if (kind === "command") {
    if (typeof payload.name !== "string" || payload.name.length === 0) errors.push("command payload requires a non-empty name");
    if (payload.args !== undefined && (!Array.isArray(payload.args) || payload.args.some((arg) => typeof arg !== "string"))) {
      errors.push("command payload args must be a string array");
    }
  } else if (kind === "intent") {
    if (typeof payload.text !== "string" || payload.text.length === 0) errors.push("intent payload requires non-empty text");
  } else if (kind === "result") {
    if (typeof payload.success !== "boolean") errors.push("result payload requires boolean success");
  } else if (kind === "stream_chunk") {
    if (typeof payload.data !== "string") errors.push("stream_chunk payload requires string data");
  } else if (kind === "control") {
    if (typeof payload.op !== "string" || !(CONTROL_KINDS as readonly string[]).includes(payload.op)) {
      errors.push(`control payload has unknown op: ${String(payload.op)}`);
    }
    if (payload.session_id !== undefined && (typeof payload.session_id !== "string" || payload.session_id.length === 0)) {
      errors.push("control payload session_id must be a non-empty string");
    }
    if (payload.last_acked !== undefined && !isInteger(payload.last_acked, -1)) {
      errors.push("control payload last_acked must be an integer >= -1");
    }
  } else if (kind === "ack" && !isInteger(payload.ack_seq)) {
    errors.push("ack payload requires a non-negative integer ack_seq");
  }
  return errors;
}

export function validateMessage(message: unknown): string[] {
  /** Return validation errors; an empty array means the message is valid. */
  if (!isObject(message)) return ["envelope must be an object"];
  const errors: string[] = [];
  for (const field of ["v", "session_id", "seq", "ts", "kind", "payload"]) {
    if (!(field in message)) errors.push(`missing field: ${field}`);
  }
  if (errors.length > 0) return errors;
  if (message.v !== PROTOCOL_VERSION) errors.push(`unsupported version: ${String(message.v)}`);
  if (typeof message.session_id !== "string" || message.session_id.length === 0) errors.push("session_id must be a non-empty string");
  if (!isInteger(message.seq)) errors.push("seq must be a non-negative integer");
  if (typeof message.kind !== "string" || !(KINDS as readonly string[]).includes(message.kind)) {
    errors.push(`unknown kind: ${String(message.kind)}`);
  }
  if (typeof message.ts !== "number" || !Number.isFinite(message.ts)) errors.push("ts must be a number");
  if ("trace_id" in message && typeof message.trace_id !== "string") errors.push("trace_id must be a string");
  if (!isObject(message.payload)) errors.push("payload must be an object");
  else if (typeof message.kind === "string" && (KINDS as readonly string[]).includes(message.kind)) {
    errors.push(...validatePayload(message.kind as MessageKind, message.payload));
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

export class Outbox {
  /** Maintain the bounded per-session replay window (Python mirror). */
  private readonly items: Message[] = [];
  private acknowledged = -1;

  constructor(public readonly maxlen = OUTBOX_MAXLEN) {
    if (!Number.isInteger(maxlen) || maxlen < 1) throw new Error("maxlen must be a positive integer");
  }

  append(message: Message): void {
    this.items.push(message);
    while (this.items.length > this.maxlen) this.items.shift();
  }

  /**
   * Non-destructive ack, mirroring the Python host: only the acknowledged
   * cursor advances; retained messages let a lagging view keep replaying.
   */
  ack(seq: number): void {
    this.acknowledged = Math.max(this.acknowledged, seq);
  }

  /** Replay window for one view cursor (messages after afterSeq). */
  unacked(afterSeq?: number): Message[] {
    const after = afterSeq ?? this.acknowledged;
    return this.items.filter((message) => message.seq > after);
  }

  get lastAcked(): number {
    return this.acknowledged;
  }
}

export class SessionCursor {
  /** Track one frontend view's attachment and acknowledgement cursor. */
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

  /** Advance this view's acknowledged position (Python mirror). */
  ack(seq: number): void {
    this.lastAcked = Math.max(this.lastAcked, seq);
  }
}
