/**
 * Bounded scheduling contracts for the TypeScript L3 rewrite.
 *
 * Scheduling here is an intent/data boundary. Queue ownership, admission
 * policy, fairness, and any process execution remain injected host concerns;
 * no scheduler request can directly mount a terminal or invoke a tool.
 */

import type { JsonObject } from "../../protocol/wire-records.ts";
import type { AgentIdentity } from "../contracts/agent-contracts.ts";
import { AgentRuntimeError, copyAgentIdentity, copyJsonObject } from "../contracts/agent-contracts.ts";

/** Scope used by a scheduling request for deduplication and policy lookup. */
export type ScheduleScope = "agent" | "cell" | "session";

/** Provider-produced scheduling action before identity binding. */
export interface ScheduleRequestAction {
  readonly kind: "schedule_request";
  readonly actionId: string;
  readonly taskId: string;
  readonly queue: string;
  readonly priority: number;
  readonly notBefore: number;
  readonly deadline?: number | null;
  readonly scope: ScheduleScope;
  readonly estimatedCost?: number;
  readonly metadata?: JsonObject;
}

/** Identity-bound scheduling request submitted to the injected L3 scheduler port. */
export interface ScheduleRequest {
  readonly requestId: string;
  readonly identity: AgentIdentity;
  readonly traceId: string;
  readonly taskId: string;
  readonly queue: string;
  readonly priority: number;
  readonly notBefore: number;
  readonly deadline: number | null;
  readonly scope: ScheduleScope;
  readonly estimatedCost: number;
  readonly metadata?: JsonObject;
}

/** Result returned by an injected scheduler coordinator/host. */
export interface ScheduleReceipt {
  readonly requestId: string;
  readonly taskId: string;
  readonly traceId: string;
  readonly accepted: boolean;
  readonly status: "queued" | "rejected";
  readonly position?: number;
  readonly error?: string;
}

/** Port for L3 scheduling coordination; it has no direct process authority. */
export interface ScheduleRequestPort {
  readonly authority: "typescript";
  submitScheduleRequest(request: ScheduleRequest, signal?: AbortSignal): Promise<ScheduleReceipt>;
}

/** Maximum queue-name UTF-8 bytes. */
export const L3_MAX_SCHEDULE_QUEUE_BYTES = 128;
/** Maximum task-id UTF-8 bytes. */
export const L3_MAX_SCHEDULE_TASK_BYTES = 256;
/** Maximum priority admitted before host policy evaluation. */
export const L3_MAX_SCHEDULE_PRIORITY = 1000;
/** Maximum estimated cost units admitted from a provider. */
export const L3_MAX_SCHEDULE_COST = 1_000_000;
/** Maximum metadata UTF-8 bytes. */
export const L3_MAX_SCHEDULE_METADATA_BYTES = 8 * 1024;

/** Convert a provider action into a detached, identity-bound schedule request. */
export function scheduleRequestFromAction(
  action: ScheduleRequestAction,
  identity: AgentIdentity,
  traceId: string,
): ScheduleRequest {
  validateScheduleRequestActionShape(action);
  const requestId = requireText(action.actionId, "schedule action.actionId");
  const taskId = boundedText(action.taskId, "schedule action.taskId", L3_MAX_SCHEDULE_TASK_BYTES);
  const queue = boundedText(action.queue, "schedule action.queue", L3_MAX_SCHEDULE_QUEUE_BYTES);
  const priority = boundedInteger(action.priority, "schedule action.priority", 0, L3_MAX_SCHEDULE_PRIORITY);
  const notBefore = finiteTime(action.notBefore, "schedule action.notBefore");
  const deadline = action.deadline === undefined || action.deadline === null
    ? null
    : finiteTime(action.deadline, "schedule action.deadline");
  if (deadline !== null && deadline < notBefore) {
    throw new AgentRuntimeError("invalid_coordination", "schedule deadline cannot precede notBefore");
  }
  const scope = requireEnum(action.scope, ["agent", "cell", "session"] as const, "schedule action.scope");
  const estimatedCost = action.estimatedCost === undefined
    ? 1
    : boundedInteger(action.estimatedCost, "schedule action.estimatedCost", 1, L3_MAX_SCHEDULE_COST);
  const metadata = action.metadata === undefined ? undefined : copyMetadata(action.metadata);
  return {
    requestId,
    identity: copyAgentIdentity(identity),
    traceId: requireText(traceId, "schedule request.traceId", true),
    taskId,
    queue,
    priority,
    notBefore,
    deadline,
    scope,
    estimatedCost,
    metadata,
  };
}

/** Validate and detach a scheduler receipt before exposing it to AgentRuntime. */
export function copyScheduleReceipt(
  receipt: ScheduleReceipt,
  request: ScheduleRequest,
): ScheduleReceipt {
  if (!isRecord(receipt)) {
    throw new AgentRuntimeError("invalid_receipt", "schedule receipt must be an object");
  }
  if (receipt.requestId !== request.requestId || receipt.taskId !== request.taskId) {
    throw new AgentRuntimeError("invalid_receipt", "schedule receipt does not match the submitted request");
  }
  if (receipt.traceId !== request.traceId) {
    throw new AgentRuntimeError("invalid_receipt", "schedule receipt trace id does not match the submitted request");
  }
  if (typeof receipt.accepted !== "boolean" || (receipt.accepted && receipt.status !== "queued")
    || (!receipt.accepted && receipt.status !== "rejected")) {
    throw new AgentRuntimeError("invalid_receipt", "schedule receipt acceptance and status are inconsistent");
  }
  if (receipt.position !== undefined
    && (!Number.isSafeInteger(receipt.position) || receipt.position < 0)) {
    throw new AgentRuntimeError("invalid_receipt", "schedule receipt position must be a non-negative safe integer");
  }
  if (receipt.status === "rejected" && (typeof receipt.error !== "string" || receipt.error.length === 0)) {
    throw new AgentRuntimeError("invalid_receipt", "schedule rejection must include an error");
  }
  return {
    requestId: request.requestId,
    taskId: request.taskId,
    traceId: request.traceId,
    accepted: receipt.accepted,
    status: receipt.status,
    position: receipt.position,
    error: receipt.error,
  };
}

/** Validate the shallow action shape before a provider decision is admitted. */
export function validateScheduleRequestActionShape(action: ScheduleRequestAction): void {
  if (!isRecord(action) || action.kind !== "schedule_request") {
    throw new AgentRuntimeError("invalid_decision", "schedule action must be a schedule_request object");
  }
  requireText(action.actionId, "schedule action.actionId");
  boundedText(action.taskId, "schedule action.taskId", L3_MAX_SCHEDULE_TASK_BYTES);
  boundedText(action.queue, "schedule action.queue", L3_MAX_SCHEDULE_QUEUE_BYTES);
  boundedInteger(action.priority, "schedule action.priority", 0, L3_MAX_SCHEDULE_PRIORITY);
  finiteTime(action.notBefore, "schedule action.notBefore");
  if (action.deadline !== undefined && action.deadline !== null) finiteTime(action.deadline, "schedule action.deadline");
  requireEnum(action.scope, ["agent", "cell", "session"] as const, "schedule action.scope");
  if (action.estimatedCost !== undefined) {
    boundedInteger(action.estimatedCost, "schedule action.estimatedCost", 1, L3_MAX_SCHEDULE_COST);
  }
  if (action.metadata !== undefined) copyMetadata(action.metadata);
}

function copyMetadata(value: unknown): JsonObject {
  if (!isJsonObject(value) || !isJsonValue(value)) {
    throw new AgentRuntimeError("invalid_coordination", "schedule metadata must be a finite JSON object");
  }
  if (utf8Bytes(JSON.stringify(value)) > L3_MAX_SCHEDULE_METADATA_BYTES) {
    throw new AgentRuntimeError("schedule_limit", "schedule metadata exceeds the configured byte bound");
  }
  return copyJsonObject(value);
}

function boundedText(value: unknown, name: string, maxBytes: number): string {
  const text = requireText(value, name);
  if (utf8Bytes(text) > maxBytes) {
    throw new AgentRuntimeError("schedule_limit", `${name} exceeds the configured byte bound`);
  }
  return text;
}

function boundedInteger(value: unknown, name: string, minimum: number, maximum: number): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new AgentRuntimeError("invalid_coordination", `${name} must be a safe integer in range`);
  }
  return value as number;
}

function finiteTime(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new AgentRuntimeError("invalid_coordination", `${name} must be a finite non-negative number`);
  }
  return value;
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
