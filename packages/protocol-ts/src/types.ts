/**
 * Type-safe branded primitives and discriminated payload unions for the
 * L2 protocol v1 wire contract (TS mirror of src/l2/protocol/envelope.py).
 *
 * Design goals:
 *   - Branded IDs prevent accidental cross-assignment of string identifiers
 *   - Discriminated payload union gives exhaustive switch narrowing at the
 *     type level, replacing the runtime-only kind checks in validatePayload
 *   - Readonly constraints enforce immutability at the consumer boundary
 *
 * TS-mirror note: every type here has a 1:1 Python3 counterpart documented
 * in src/l2/protocol/envelope.py; field names use snake_case to match the
 * wire format exactly (no camelCase translation layer).
 */

/** Minimal JSON value type (local alias to avoid cross-module circularity). */
export type _JsonValue = string | number | boolean | null | { [key: string]: _JsonValue } | _JsonValue[];
export type _JsonObject = { [key: string]: _JsonValue };

// ── Branded primitives ──────────────────────────────────────────────────
// Each branded type wraps a primitive with a phantom tag so that two
// structurally identical strings cannot be accidentally interchanged.

declare const __brand_SessionId: unique symbol;
declare const __brand_ViewId: unique symbol;
declare const __brand_TraceId: unique symbol;

/** A unique session identifier (branded string). */
export type SessionId = string & { readonly [__brand_SessionId]: true };
/** A frontend view identifier within one session (branded string). */
export type ViewId = string & { readonly [__brand_ViewId]: true };
/** A distributed trace correlation id (branded string). */
export type TraceId = string & { readonly [__brand_TraceId]: true };

/** Lift a raw string into a branded SessionId (no runtime cost). */
export function asSessionId(raw: string): SessionId {
  return raw as SessionId;
}

/** Lift a raw string into a branded ViewId (no runtime cost). */
export function asViewId(raw: string): ViewId {
  return raw as ViewId;
}

/** Lift a raw string into a branded TraceId (empty string allowed = no trace). */
export function asTraceId(raw: string): TraceId | "" {
  return raw as TraceId | "";
}

// ── Protocol constants ──────────────────────────────────────────────────

export const PROTOCOL_VERSION = 1 as const;
export const OUTBOX_MAXLEN = 1024;

export const KINDS = ["ack", "command", "control", "event", "intent", "result", "stream_chunk"] as const;
export type MessageKind = (typeof KINDS)[number];

export const CONTROL_OPS = ["attach", "detach", "resume", "recovery", "ack"] as const;
export type ControlOp = (typeof CONTROL_OPS)[number];

// ── Per-kind payload shapes (discriminated by `kind`) ──────────────────
// Each interface documents the exact fields the Python3 host expects for
// that message kind. Using a discriminated union instead of a generic
// _JsonObject gives compile-time exhaustiveness checking in switch blocks.

export interface AckPayload {
  ack_seq: number;
  view_id?: string;
}

export interface CommandPayload {
  name: string;
  args?: readonly string[];
}

export interface ControlPayload {
  op: ControlOp;
  session_id?: string;
  view_id?: string;
  last_acked?: number;
}

export interface EventPayload {
  event_type: string;
  data?: _JsonObject;
}

export interface IntentPayload {
  text: string;
  [key: string]: _JsonValue;
}

export interface ResultPayload {
  success: boolean;
  output?: string;
  error?: string;
  [key: string]: _JsonValue;
}

export interface StreamChunkPayload {
  data: string;
  done?: boolean;
}

// ── Discriminated message union ────────────────────────────────────────
// The base fields are shared; `kind` acts as the discriminant. Consumers
// can switch on `msg.kind` and get fully typed payloads without casting.

interface MessageBase {
  v: typeof PROTOCOL_VERSION;
  session_id: SessionId;
  seq: number;
  ts: number;
}

export interface AckMessage extends MessageBase {
  kind: "ack";
  payload: AckPayload;
}
export interface CommandMessage extends MessageBase {
  kind: "command";
  payload: CommandPayload;
  trace_id?: TraceId | "";
}
export interface ControlMessage extends MessageBase {
  kind: "control";
  payload: ControlPayload;
}
export interface EventMessage extends MessageBase {
  kind: "event";
  payload: EventPayload;
}
export interface IntentMessage extends MessageBase {
  kind: "intent";
  payload: IntentPayload;
  trace_id?: TraceId | "";
}
export interface ResultMessage extends MessageBase {
  kind: "result";
  payload: ResultPayload;
}
export interface StreamChunkMessage extends MessageBase {
  kind: "stream_chunk";
  payload: StreamChunkPayload;
}

/** Discriminated union of all protocol v1 message kinds. */
export type TypedMessage =
  | AckMessage
  | CommandMessage
  | ControlMessage
  | EventMessage
  | IntentMessage
  | ResultMessage
  | StreamChunkMessage;

// ── Legacy compatibility ────────────────────────────────────────────────
// The original Message interface used loose types. Re-export it as a
// deprecated alias so existing consumers migrate incrementally.

import type { _JsonObject } from "./records.ts";

/**
 * @deprecated Use {@link TypedMessage} for new code. This loose interface
 * matches any kind and requires runtime validation via validateMessage().
 */
export interface Message {
  v: typeof PROTOCOL_VERSION;
  session_id: string;
  seq: number;
  ts: number;
  trace_id?: string;
  kind: MessageKind;
  payload: _JsonObject;
}

/** Re-export JSON types from records.ts for single-import convenience. */
export type { _JsonObject, _JsonValue } from "./records.ts";

// ── Validation result ───────────────────────────────────────────────────

export interface DecodedMessage {
  message: Message | null;
  error: string | null;
}

// ── Internal helpers ────────────────────────────────────────────────────

function isObject(value: unknown): value is _JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}

function nowSeconds(): number {
  return Date.now() / 1000;
}
