/**
 * Read-only Memory/Prompt context projection for the TypeScript L3 boundary.
 *
 * Only bounded identity-scoped digest references cross into the provider
 * context. The projection carries no prompt text, Python objects, stores, or
 * mutation callbacks; loading and persistence remain host-owned concerns.
 */

import type { JsonObject } from "../../protocol/wire-records.ts";
import type { AgentIdentity, AgentInput } from "../contracts/agent-contracts.ts";
import { AgentRuntimeError, copyAgentIdentity, copyJsonObject } from "../contracts/agent-contracts.ts";

/** Maximum digest references exposed for one decision. */
export const L3_MAX_CONTEXT_REFS = 64;
/** Maximum aggregate source bytes represented by one context projection. */
export const L3_MAX_CONTEXT_BYTES = 128 * 1024;

/** Context source classes mirrored from the Python reference layers. */
export type ContextSource = "memory" | "prompt" | "history" | "system";

/** Metadata-only digest reference; it never carries source content. */
export interface ContextDigestRef {
  readonly refId: string;
  readonly source: ContextSource;
  readonly digest: string;
  readonly bytes: number;
  readonly metadata?: JsonObject;
}

/** Identity-bound, read-only context supplied to a provider. */
export interface AgentContextProjection {
  readonly identity: AgentIdentity;
  readonly refs: readonly ContextDigestRef[];
  readonly totalBytes: number;
  readonly truncated: boolean;
}

/** Host-owned read-only context loader. */
export interface ReadOnlyContextPort {
  load(
    identity: AgentIdentity,
    input: AgentInput,
    signal?: AbortSignal,
  ): Promise<AgentContextProjection>;
}

/** Validate and detach one context projection before provider admission. */
export function copyContextProjection(
  context: AgentContextProjection,
  identity: AgentIdentity,
  limits: { readonly maxRefs?: number; readonly maxBytes?: number } = {},
): AgentContextProjection {
  if (!context || typeof context !== "object" || Array.isArray(context)) {
    throw new AgentRuntimeError("context_failed", "context projection must be an object");
  }
  if (!sameIdentity(context.identity, identity)) {
    throw new AgentRuntimeError("context_failed", "context projection identity does not match the Agent identity");
  }
  const maxRefs = positiveLimit(limits.maxRefs ?? L3_MAX_CONTEXT_REFS, "maxRefs");
  const maxBytes = positiveLimit(limits.maxBytes ?? L3_MAX_CONTEXT_BYTES, "maxBytes");
  if (!Array.isArray(context.refs) || context.refs.length > maxRefs) {
    throw new AgentRuntimeError("context_limit", "context reference count exceeds the configured bound");
  }
  const refs: ContextDigestRef[] = [];
  const seen = new Set<string>();
  let totalBytes = 0;
  for (const [index, ref] of context.refs.entries()) {
    if (!ref || typeof ref !== "object" || Array.isArray(ref)) {
      throw new AgentRuntimeError("context_failed", `context reference ${index} must be an object`);
    }
    const candidate = ref as ContextDigestRef;
    const refId = requireText(candidate.refId, `context reference ${index}.refId`);
    const source = candidate.source;
    if (!["memory", "prompt", "history", "system"].includes(source)) {
      throw new AgentRuntimeError("context_failed", `context reference ${index}.source is unsupported`);
    }
    const digest = requireText(candidate.digest, `context reference ${index}.digest`);
    if (!Number.isSafeInteger(candidate.bytes) || candidate.bytes < 0) {
      throw new AgentRuntimeError("context_failed", `context reference ${index}.bytes must be a non-negative safe integer`);
    }
    if (seen.has(refId)) {
      throw new AgentRuntimeError("context_failed", `duplicate context reference: ${refId}`);
    }
    seen.add(refId);
    totalBytes += candidate.bytes;
    if (totalBytes > maxBytes) {
      throw new AgentRuntimeError("context_limit", "context projection exceeds the configured byte bound");
    }
    if (candidate.metadata !== undefined && (!isJsonObject(candidate.metadata) || !isJsonValue(candidate.metadata))) {
      throw new AgentRuntimeError("context_failed", `context reference ${index}.metadata must be a JSON object`);
    }
    refs.push({
      refId,
      source,
      digest,
      bytes: candidate.bytes,
      metadata: candidate.metadata ? copyJsonObject(candidate.metadata) : undefined,
    });
  }
  if (!Number.isSafeInteger(context.totalBytes) || context.totalBytes < 0 || context.totalBytes !== totalBytes) {
    throw new AgentRuntimeError("context_failed", "context totalBytes does not match its references");
  }
  if (typeof context.truncated !== "boolean") {
    throw new AgentRuntimeError("context_failed", "context truncated must be a boolean");
  }
  return {
    identity: copyAgentIdentity(identity),
    refs,
    totalBytes,
    truncated: context.truncated,
  };
}

function sameIdentity(left: AgentIdentity, right: AgentIdentity): boolean {
  return Boolean(left)
    && left.agentId === right.agentId
    && left.cellId === right.cellId
    && left.sessionId === right.sessionId
    && left.terminalId === right.terminalId;
}

function isJsonObject(value: unknown): value is JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  return Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null;
}

function isJsonValue(value: unknown, ancestors: WeakSet<object> = new WeakSet<object>()): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "object") return false;
  if (ancestors.has(value)) return false;
  ancestors.add(value);
  const valid = Array.isArray(value)
    ? value.every((item) => isJsonValue(item, ancestors))
    : isJsonObject(value) && Object.values(value).every((item) => isJsonValue(item, ancestors));
  ancestors.delete(value);
  return valid;
}

function requireText(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0 || value.includes("\0")) {
    throw new AgentRuntimeError("context_failed", `${name} must be a non-empty string`);
  }
  return value;
}

function positiveLimit(value: number, name: string): number {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new AgentRuntimeError("context_limit", `${name} must be a positive safe integer`);
  }
  return value;
}
