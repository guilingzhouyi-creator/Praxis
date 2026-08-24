/**
 * Type-safe branded primitives and discriminated payload unions for the
 * L2 protocol v1 wire contract (TS mirror of src/l2/protocol/envelope.py).
 */

import type { JsonObject } from "./records.ts";

// Re-export for single-import convenience.
export type { JsonObject };

// ── Branded primitives ────────────────────────────────────────────────

declare const __brand_SessionId: unique symbol;
declare const __brand_ViewId: unique symbol;

/** Branded session identifier — prevents cross-assignment with other string IDs. */
export type SessionId = string & { readonly [__brand_SessionId]: true };
/** Branded frontend view identifier within one session. */
export type ViewId = string & { readonly [__brand_ViewId]: true };

/** Lift a raw string into a branded SessionId (zero runtime cost). */
export function asSessionId(raw: string): SessionId { return raw as SessionId; }
/** Lift a raw string into a branded ViewId (no runtime cost). */
export function asViewId(raw: string): ViewId { return raw as ViewId; }

// ── Protocol constants ────────────────────────────────────────────────

/** Protocol wire format version (v1). */
export const PROTOCOL_VERSION = 1 as const;
/** Maximum number of messages retained in the per-session replay window. */
export const OUTBOX_MAXLEN = 1024;
/** All valid message kind discriminants. */
export const KINDS = ["ack","command","control","event","intent","result","stream_chunk"] as const;
/** Union of all message kind discriminants. */
export type MessageKind = (typeof KINDS)[number];
/** Valid control operations for session lifecycle management. */
export const CONTROL_OPS = ["attach","detach","resume","recovery","ack"] as const;
/** Union of control operation names. */
export type ControlOp = (typeof CONTROL_OPS)[number];

/**
 * Wire-contract constants are exempt from the params rule and inlined
 * identically in all three implementations (ruling R8).
 */
/** Maximum accepted JSONL frame size per host (1 MiB, ruling R5). */
export const MAX_FRAME_BYTES = 1024 * 1024 as const;
/** Truncation cap applied to `$` system command output (rendering layer). */
export const SYSTEM_OUTPUT_MAX_CHARS = 64_000 as const;
/**
 * Host-derived authorization fields banned from inbound payloads (R4):
 * they are GateRequest inputs derived by identity/posture adapters and
 * must never travel on the wire.
 */
export const HOST_DERIVED_FIELDS: readonly string[] = [
  "approved",
  "pre_approved",
  "full_power",
  "harness_auto_approved",
] as const;

// ── Per-kind payloads ─────────────────────────────────────────────────

/** Acknowledgement: confirms receipt up to `ack_seq` for one view. */
export interface AckPayload { ack_seq: number; view_id?: string }
/** Command dispatch: named command with string arguments. */
export interface CommandPayload { name: string; args?: readonly string[] }
/** Control operation: session lifecycle (attach/detach/resume/recovery/ack). */
export interface ControlPayload {
  op: ControlOp; session_id?: string; view_id?: string; last_acked?: number;
}
/** Event notification: typed event with optional structured data. */
export interface EventPayload { event_type: string; data?: JsonObject }
/** Intent: natural language input routed to the L3A decision layer. */
export interface IntentPayload { text: string; [key: string]: string | number | boolean | null | undefined }
/** Result: command/intent execution outcome. */
export interface ResultPayload {
  success: boolean; output?: string; error?: string;
  [key: string]: string | number | boolean | null | undefined;
}
/** Stream chunk: incremental output fragment for progressive rendering. */
export interface StreamChunkPayload { data: string; done?: boolean }

// ── Discriminated message union ───────────────────────────────────────

/** Shared envelope fields common to every message kind. */
interface MessageBase {
  v: typeof PROTOCOL_VERSION;
  session_id: string;
  seq: number;
  ts: number;
}

export interface AckMessage extends MessageBase { kind: "ack"; payload: AckPayload }
export interface CommandMessage extends MessageBase { kind: "command"; payload: CommandPayload; trace_id?: string }
export interface ControlMessage extends MessageBase { kind: "control"; payload: ControlPayload }
export interface EventMessage extends MessageBase { kind: "event"; payload: EventPayload }
export interface IntentMessage extends MessageBase { kind: "intent"; payload: IntentPayload; trace_id?: string }
export interface ResultMessage extends MessageBase { kind: "result"; payload: ResultPayload }
export interface StreamChunkMessage extends MessageBase { kind: "stream_chunk"; payload: StreamChunkPayload }

export type TypedMessage =
  | AckMessage | CommandMessage | ControlMessage | EventMessage
  | IntentMessage | ResultMessage | StreamChunkMessage;

// ── Validation result ─────────────────────────────────────────────────

export interface DecodedMessage {
  message: Message | null;
  error: string | null;
}

// ── Loose legacy interface (deprecated) ───────────────────────────────

/** @deprecated Use TypedMessage for new code. */
export interface Message {
  v: typeof PROTOCOL_VERSION;
  session_id: string;
  seq: number;
  ts: number;
  trace_id?: string;
  kind: MessageKind;
  payload: JsonObject;
}
