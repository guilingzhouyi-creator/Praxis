/**
 * Data-only card coordination contracts for the TypeScript L3 rewrite.
 *
 * Card lifecycle policy remains an injected L3 concern. This module never
 * opens a store, invokes a tool, or owns a Rust process. Skill/TODO/evidence
 * links cross the boundary as bounded identifiers only.
 */

import type { JsonObject } from "../../protocol/wire-records.ts";
import type { AgentIdentity } from "../contracts/agent-contracts.ts";
import { AgentRuntimeError, copyAgentIdentity, copyJsonObject } from "../contracts/agent-contracts.ts";

/** Card lifecycle operations admitted by the clean-break coordinator. */
export type CardIntentOperation = "produce" | "execute" | "approve" | "archive" | "reject";

/** Optional lifecycle hint carried with an intent; the host remains authoritative. */
export type CardLifecycleHint = "draft" | "ready" | "approved" | "executing" | "completed" | "archived" | "rejected";

/** Bounded cross-domain references; values are IDs, never object handles. */
export interface CardLinkProjection {
  readonly skillIds: readonly string[];
  readonly todoIds: readonly string[];
  readonly evidenceRefs: readonly string[];
}

/** A provider-produced card action before identity binding. */
export interface CardIntentAction {
  readonly kind: "card_intent";
  readonly actionId: string;
  readonly cardId: string;
  readonly operation: CardIntentOperation;
  readonly title?: string;
  readonly lifecycle?: CardLifecycleHint;
  readonly links?: CardLinkProjection;
  readonly data?: JsonObject;
}

/** Identity-bound card intent submitted to the injected L3 card port. */
export interface CardIntent {
  readonly intentId: string;
  readonly identity: AgentIdentity;
  readonly traceId: string;
  readonly cardId: string;
  readonly operation: CardIntentOperation;
  readonly title: string;
  readonly lifecycle?: CardLifecycleHint;
  readonly links: CardLinkProjection;
  readonly data?: JsonObject;
}

/** Result returned by an injected card coordinator/host. */
export interface CardIntentReceipt {
  readonly intentId: string;
  readonly cardId: string;
  readonly traceId: string;
  readonly accepted: boolean;
  readonly status: "accepted" | "rejected";
  readonly error?: string;
  readonly data?: JsonObject;
}

/** Port for card lifecycle coordination; it has no process authority. */
export interface CardIntentPort {
  readonly authority: "typescript";
  submitCardIntent(intent: CardIntent, signal?: AbortSignal): Promise<CardIntentReceipt>;
}

/** Maximum UTF-8 bytes in a card title. */
export const L3_MAX_CARD_TITLE_BYTES = 4 * 1024;
/** Maximum UTF-8 bytes in the data projection attached to one card intent. */
export const L3_MAX_CARD_DATA_BYTES = 16 * 1024;
/** Maximum number of IDs in one link family. */
export const L3_MAX_CARD_LINK_IDS = 32;

/** Convert a provider action into a detached, identity-bound card intent. */
export function cardIntentFromAction(
  action: CardIntentAction,
  identity: AgentIdentity,
  traceId: string,
): CardIntent {
  if (!isRecord(action) || action.kind !== "card_intent") {
    throw new AgentRuntimeError("invalid_coordination", "card action must be a card_intent object");
  }
  const intentId = requireText(action.actionId, "card action.actionId");
  const cardId = requireText(action.cardId, "card action.cardId");
  const operation = requireEnum(
    action.operation,
    ["produce", "execute", "approve", "archive", "reject"] as const,
    "card action.operation",
  );
  const title = action.title === undefined ? "" : requireText(action.title, "card action.title", true);
  if (operation === "produce" && title.length === 0) {
    throw new AgentRuntimeError("invalid_coordination", "card produce action requires a title");
  }
  if (utf8Bytes(title) > L3_MAX_CARD_TITLE_BYTES) {
    throw new AgentRuntimeError("card_limit", "card title exceeds the configured byte bound");
  }
  const lifecycle = action.lifecycle === undefined
    ? undefined
    : requireEnum(
      action.lifecycle,
      ["draft", "ready", "approved", "executing", "completed", "archived", "rejected"] as const,
      "card action.lifecycle",
    );
  const links = copyCardLinks(action.links);
  const data = action.data === undefined ? undefined : copyBoundedJsonObject(action.data);
  return {
    intentId,
    identity: copyAgentIdentity(identity),
    traceId: requireText(traceId, "card intent.traceId", true),
    cardId,
    operation,
    title,
    lifecycle,
    links,
    data,
  };
}

/** Validate and detach a card receipt before it is exposed to AgentRuntime. */
export function copyCardIntentReceipt(
  receipt: CardIntentReceipt,
  intent: CardIntent,
): CardIntentReceipt {
  if (!isRecord(receipt)) {
    throw new AgentRuntimeError("invalid_receipt", "card receipt must be an object");
  }
  if (receipt.intentId !== intent.intentId || receipt.cardId !== intent.cardId) {
    throw new AgentRuntimeError("invalid_receipt", "card receipt does not match the submitted intent");
  }
  if (receipt.traceId !== intent.traceId) {
    throw new AgentRuntimeError("invalid_receipt", "card receipt trace id does not match the submitted intent");
  }
  if (typeof receipt.accepted !== "boolean" || (receipt.accepted && receipt.status !== "accepted")
    || (!receipt.accepted && receipt.status !== "rejected")) {
    throw new AgentRuntimeError("invalid_receipt", "card receipt acceptance and status are inconsistent");
  }
  if (receipt.status === "rejected" && (typeof receipt.error !== "string" || receipt.error.length === 0)) {
    throw new AgentRuntimeError("invalid_receipt", "card rejection must include an error");
  }
  const data = receipt.data === undefined ? undefined : copyBoundedJsonObject(receipt.data, "card receipt data");
  return {
    intentId: intent.intentId,
    cardId: intent.cardId,
    traceId: intent.traceId,
    accepted: receipt.accepted,
    status: receipt.status,
    error: receipt.error,
    data,
  };
}

/** Validate the shallow action shape before a provider decision is admitted. */
export function validateCardIntentActionShape(action: CardIntentAction): void {
  if (!isRecord(action) || action.kind !== "card_intent") {
    throw new AgentRuntimeError("invalid_decision", "card action must be a card_intent object");
  }
  requireText(action.actionId, "card action.actionId");
  requireText(action.cardId, "card action.cardId");
  requireEnum(
    action.operation,
    ["produce", "execute", "approve", "archive", "reject"] as const,
    "card action.operation",
  );
  if (action.title !== undefined) requireText(action.title, "card action.title", true);
  if (action.lifecycle !== undefined) {
    requireEnum(
      action.lifecycle,
      ["draft", "ready", "approved", "executing", "completed", "archived", "rejected"] as const,
      "card action.lifecycle",
    );
  }
  if (action.links !== undefined) copyCardLinks(action.links);
  if (action.data !== undefined) copyBoundedJsonObject(action.data);
}

function copyCardLinks(value: unknown): CardLinkProjection {
  if (value === undefined) return { skillIds: [], todoIds: [], evidenceRefs: [] };
  if (!isRecord(value)) {
    throw new AgentRuntimeError("invalid_coordination", "card links must be an object");
  }
  return {
    skillIds: copyIdList(value.skillIds, "card links.skillIds"),
    todoIds: copyIdList(value.todoIds, "card links.todoIds"),
    evidenceRefs: copyIdList(value.evidenceRefs, "card links.evidenceRefs"),
  };
}

function copyIdList(value: unknown, name: string): readonly string[] {
  if (!Array.isArray(value) || value.length > L3_MAX_CARD_LINK_IDS) {
    throw new AgentRuntimeError("card_limit", `${name} exceeds the configured count bound`);
  }
  const result = value.map((item, index) => requireText(item, `${name}[${index}]`));
  if (new Set(result).size !== result.length) {
    throw new AgentRuntimeError("invalid_coordination", `${name} cannot contain duplicate identifiers`);
  }
  return result;
}

function copyBoundedJsonObject(value: unknown, name = "card action data"): JsonObject {
  if (!isJsonObject(value) || !isJsonValue(value)) {
    throw new AgentRuntimeError("invalid_coordination", `${name} must be a finite JSON object`);
  }
  if (utf8Bytes(JSON.stringify(value)) > L3_MAX_CARD_DATA_BYTES) {
    throw new AgentRuntimeError("card_limit", `${name} exceeds the configured byte bound`);
  }
  return copyJsonObject(value);
}

function requireText(value: unknown, name: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0) || value.includes("\0")) {
    throw new AgentRuntimeError("invalid_coordination", `${name} must be a valid ${allowEmpty ? "string" : "non-empty string"}`);
  }
  return value;
}

function requireEnum<const T extends readonly string[]>(
  value: unknown,
  values: T,
  name: string,
): T[number] {
  if (typeof value !== "string" || !values.includes(value)) {
    throw new AgentRuntimeError("invalid_coordination", `${name} is unsupported`);
  }
  return value as T[number];
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}

function isJsonValue(value: unknown, ancestors: WeakSet<object> = new WeakSet<object>()): value is JsonObject {
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
