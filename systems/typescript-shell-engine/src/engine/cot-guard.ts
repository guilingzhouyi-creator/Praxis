/**
 * CoT privacy guard — ensures chain-of-thought never crosses the protocol
 * boundary (P2.3 of agent-os-3x-closure roadmap).
 *
 * The TS engine is a projection layer: it must never see or transmit
 * reasoning text. This module provides:
 *   1. A type-level guard that strips `reasoning` fields from payloads
 *   2. A runtime sanitizer for defence-in-depth (belt + suspenders)
 *   3. An allowlist of safe payload keys per message kind
 *
 * TS pattern: `Omit<T, K>` mapped types make unsafe shapes unrepresentable.
 */

import type { JsonObject } from "../records.ts";

/** Keys that are FORBIDDEN in any outbound protocol payload (CoT vectors). */
const FORBIDDEN_KEYS = new Set([
  "reasoning",
  "reasoning_content",
  "chain_of_thought",
  "thoughts",
  "thinking",
  "reasoning_trail",
  "cot",
]);

/** Recursively strip forbidden keys from a JSON object (deep). */
export function sanitizePayload(payload: JsonObject): JsonObject {
  const clean: JsonObject = {};
  for (const [key, value] of Object.entries(payload)) {
    if (FORBIDDEN_KEYS.has(key)) continue;
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      clean[key] = sanitizePayload(value as JsonObject);
    } else if (Array.isArray(value)) {
      clean[key] = value.map((item) =>
        typeof item === "object" && item !== null ? sanitizePayload(item as JsonObject) : item,
      );
    } else {
      clean[key] = value;
    }
  }
  return clean;
}

/** Check whether a payload contains any forbidden key at any depth. */
export function containsCoT(payload: JsonObject): boolean {
  for (const [key, value] of Object.entries(payload)) {
    if (FORBIDDEN_KEYS.has(key)) return true;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item && typeof item === "object" && containsCoT(item as JsonObject)) return true;
      }
    } else if (value && typeof value === "object") {
      if (containsCoT(value as JsonObject)) return true;
    }
  }
  return false;
}

/** Allowed top-level payload keys per message kind (TS-mirrorable contract). */
export const ALLOWED_PAYLOAD_KEYS: Readonly<Record<import("../types.ts").MessageKind, ReadonlySet<string>>> =
  Object.freeze({
    ack: new Set(["ack_seq", "view_id"]),
    command: new Set(["name", "args"]),
    control: new Set(["op", "session_id", "view_id", "last_acked"]),
    event: new Set(["event_type", "data"]),
    intent: new Set(["text"]),
    result: new Set(["success", "output", "error"]),
    stream_chunk: new Set(["data", "done"]),
  } as Record<import("../types.ts").MessageKind, ReadonlySet<string>>);
