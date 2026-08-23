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

export type SessionId = string & { readonly [__brand_SessionId]: true };
export type ViewId = string & { readonly [__brand_ViewId]: true };

export function asSessionId(raw: string): SessionId { return raw as SessionId; }
export function asViewId(raw: string): ViewId { return raw as ViewId; }

// ── Protocol constants ────────────────────────────────────────────────

export const PROTOCOL_VERSION = 1 as const;
export const OUTBOX_MAXLEN = 1024;
export const KINDS = ["ack","command","control","event","intent","result","stream_chunk"] as const;
export type MessageKind = (typeof KINDS)[number];
export const CONTROL_OPS = ["attach","detach","resume","recovery","ack"] as const;
export type ControlOp = (typeof CONTROL_OPS)[number];

// ── Per-kind payloads ─────────────────────────────────────────────────

export interface AckPayload { ack_seq: number; view_id?: string }
export interface CommandPayload { name: string; args?: readonly string[] }
export interface ControlPayload {
  op: ControlOp; session_id?: string; view_id?: string; last_acked?: number;
}
export interface EventPayload { event_type: string; data?: JsonObject }
export interface IntentPayload { text: string; [key: string]: string | number | boolean | null | undefined }
export interface ResultPayload {
  success: boolean; output?: string; error?: string;
  [key: string]: string | number | boolean | null | undefined;
}
export interface StreamChunkPayload { data: string; done?: boolean }

// ── Discriminated message union ───────────────────────────────────────

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
