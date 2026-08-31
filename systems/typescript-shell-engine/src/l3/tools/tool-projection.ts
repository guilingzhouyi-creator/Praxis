/**
 * Data-only projection of the Python reference tool registry.
 *
 * A projection contains the public contract needed by a decision provider.
 * It intentionally excludes handlers, middleware, plugin objects, and other
 * executable state. Rust remains the only authority that can admit a tool
 * request or produce a side effect.
 */

import type { JsonObject } from "../../protocol/wire-records.ts";
import type {
  AgentIdentity,
  KernelExecutionRequest,
  RustExecutionReceipt,
} from "../contracts/agent-contracts.ts";
import { AgentRuntimeError, copyAgentIdentity, copyJsonObject } from "../contracts/agent-contracts.ts";

/** Maximum number of tool definitions exposed to one provider. */
export const L3_MAX_TOOL_PROJECTIONS = 128;
/** Maximum UTF-8 bytes retained for one tool description. */
export const L3_MAX_TOOL_DESCRIPTION_BYTES = 8 * 1024;
/** Maximum parameters exposed for one tool. */
export const L3_MAX_TOOL_PARAMETERS = 64;
/** Maximum UTF-8 bytes accepted for one provider tool-call argument object. */
export const L3_MAX_TOOL_ARGUMENT_BYTES = 64 * 1024;
/** Maximum UTF-8 bytes retained for one folded tool result. */
export const L3_MAX_TOOL_RESULT_BYTES = 64 * 1024;
/** Rust operation name used for tool calls crossing the execution seam. */
export const RUST_TOOL_INVOKE_OPERATION = "tool.invoke";

/** Public parameter metadata from a Python `ParamSpec`. */
export interface ToolParameterProjection {
  readonly name: string;
  readonly type: string;
  readonly required: boolean;
  readonly description: string;
}

/** Public return metadata from a Python `ReturnSpec`. */
export interface ToolReturnProjection {
  readonly type: string;
  readonly description: string;
  readonly properties: JsonObject;
}

/** Handler-free, JSON-safe tool definition exposed to a provider. */
export interface ToolSpecProjection {
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly ring: string;
  readonly danger: number;
  readonly gates: readonly string[];
  readonly parameters: readonly ToolParameterProjection[];
  readonly returns: ToolReturnProjection;
  readonly parallelSafe: boolean;
  readonly sandboxProfile: string | null;
}

/** Rust-backed tool invocation accepted from a provider decision. */
export interface ToolInvocationRequest {
  readonly callId: string;
  readonly toolName: string;
  readonly args: JsonObject;
  readonly identity: AgentIdentity;
  readonly traceId: string;
}

/** Bounded result folded from a Rust execution receipt. */
export interface ToolResultProjection {
  readonly callId: string;
  readonly toolName: string;
  readonly receiptId: string;
  readonly traceId: string;
  readonly success: boolean;
  readonly status: "completed" | "rejected";
  readonly data?: JsonObject;
  readonly error?: string;
}

/** Limits accepted by the projection and result-folding helpers. */
export interface ToolProjectionLimits {
  readonly maxTools?: number;
  readonly maxDescriptionBytes?: number;
  readonly maxParameters?: number;
  readonly maxResultBytes?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown, ancestors: WeakSet<object> = new WeakSet<object>()): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "object") return false;
  if (ancestors.has(value)) return false;
  ancestors.add(value);
  const valid = Array.isArray(value)
    ? value.every((item) => isJsonValue(item, ancestors))
    : (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
      && Object.values(value).every((item) => isJsonValue(item, ancestors));
  ancestors.delete(value);
  return valid;
}

function jsonBytes(value: unknown): number {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

function requireText(value: unknown, name: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0) || value.includes("\0")) {
    throw new AgentRuntimeError("invalid_decision", `${name} must be a valid ${allowEmpty ? "string" : "non-empty string"}`);
  }
  return value;
}

function requireSafeInteger(value: unknown, name: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    throw new AgentRuntimeError("invalid_decision", `${name} must be a safe integer >= ${minimum}`);
  }
  return value as number;
}

function positiveLimit(value: number | undefined, fallback: number, name: string): number {
  const resolved = value ?? fallback;
  if (!Number.isSafeInteger(resolved) || resolved < 1) {
    throw new AgentRuntimeError("tool_limit", `${name} must be a positive safe integer`);
  }
  return resolved;
}

function readField(record: Record<string, unknown>, camel: string, snake: string): unknown {
  return record[camel] ?? record[snake];
}

function ringNumber(ring: string): number {
  const normalized = ring.toLowerCase().replace(/-/g, "_");
  if (normalized === "ring_1" || normalized === "1") return 1;
  if (normalized === "ring_2_5" || normalized === "ring_2.5" || normalized === "2_5" || normalized === "2.5") return 2;
  if (normalized === "ring_2" || normalized === "2") return 2;
  if (normalized === "ring_3" || normalized === "3") return 3;
  throw new AgentRuntimeError("invalid_decision", `unsupported tool ring: ${ring}`);
}

function projectParameter(raw: unknown, index: number): ToolParameterProjection {
  if (!isRecord(raw)) {
    throw new AgentRuntimeError("invalid_decision", `tool parameter ${index} must be an object`);
  }
  if (raw.required !== undefined && typeof raw.required !== "boolean") {
    throw new AgentRuntimeError("invalid_decision", `tool parameter ${index}.required must be a boolean`);
  }
  return {
    name: requireText(raw.name, `tool parameter ${index}.name`),
    type: requireText(raw.type ?? "string", `tool parameter ${index}.type`),
    required: raw.required === undefined ? false : raw.required === true,
    description: requireText(raw.description ?? "", `tool parameter ${index}.description`, true),
  };
}

function projectReturns(raw: unknown): ToolReturnProjection {
  if (raw === undefined) {
    return { type: "object", description: "", properties: {} };
  }
  if (!isRecord(raw)) {
    throw new AgentRuntimeError("invalid_decision", "tool returns must be an object");
  }
  const properties = raw.properties ?? {};
  if (!isRecord(properties) || !isJsonValue(properties)) {
    throw new AgentRuntimeError("invalid_decision", "tool return properties must be a finite JSON object");
  }
  return {
    type: requireText(raw.type ?? "object", "tool returns.type"),
    description: requireText(raw.description ?? "", "tool returns.description", true),
    properties: copyJsonObject(properties as JsonObject),
  };
}

/** Project one Python-style or JSON tool definition without executable fields. */
export function projectToolSpec(
  raw: unknown,
  limits: ToolProjectionLimits = {},
): ToolSpecProjection {
  if (!isRecord(raw)) {
    throw new AgentRuntimeError("invalid_decision", "tool spec must be an object");
  }
  const description = requireText(raw.description ?? "", "tool description", true);
  const maxDescriptionBytes = positiveLimit(
    limits.maxDescriptionBytes,
    L3_MAX_TOOL_DESCRIPTION_BYTES,
    "maxDescriptionBytes",
  );
  if (jsonBytes(description) > maxDescriptionBytes) {
    throw new AgentRuntimeError("tool_limit", "tool description exceeds the configured byte bound");
  }
  const parametersRaw = readField(raw, "parameters", "params") ?? [];
  if (!Array.isArray(parametersRaw)) {
    throw new AgentRuntimeError("invalid_decision", "tool parameters must be an array");
  }
  const maxParameters = positiveLimit(limits.maxParameters, L3_MAX_TOOL_PARAMETERS, "maxParameters");
  if (parametersRaw.length > maxParameters) {
    throw new AgentRuntimeError("tool_limit", "tool parameter count exceeds the configured bound");
  }
  const parameters = parametersRaw.map((parameter, index) => projectParameter(parameter, index));
  const gatesRaw = raw.gates ?? [];
  if (!Array.isArray(gatesRaw) || gatesRaw.some((gate) => typeof gate !== "string" || gate.length === 0 || gate.includes("\0"))) {
    throw new AgentRuntimeError("invalid_decision", "tool gates must be non-empty strings");
  }
  const parallelSafe = readField(raw, "parallelSafe", "parallel_safe");
  if (parallelSafe !== undefined && typeof parallelSafe !== "boolean") {
    throw new AgentRuntimeError("invalid_decision", "tool parallel_safe must be a boolean");
  }
  const danger = requireSafeInteger(raw.danger, "tool danger");
  const sandboxProfile = readField(raw, "sandboxProfile", "sandbox_profile");
  if (sandboxProfile !== null && sandboxProfile !== undefined && typeof sandboxProfile !== "string") {
    throw new AgentRuntimeError("invalid_decision", "tool sandbox profile must be a string or null");
  }
  const ring = requireText(raw.ring, "tool ring");
  ringNumber(ring);
  return {
    name: requireText(raw.name, "tool name"),
    description,
    category: requireText(raw.category ?? "", "tool category", true),
    ring,
    danger,
    gates: [...gatesRaw],
    parameters,
    returns: projectReturns(raw.returns),
    parallelSafe: parallelSafe === true,
    sandboxProfile: (sandboxProfile ?? null) as string | null,
  };
}

/** Project a Python registry list or name-keyed JSON object deterministically. */
export function projectToolRegistry(
  raw: unknown,
  limits: ToolProjectionLimits = {},
): ToolSpecProjection[] {
  const entries: unknown[] = Array.isArray(raw)
    ? raw
    : isRecord(raw)
      ? Object.values(raw)
      : [];
  if (!Array.isArray(raw) && !isRecord(raw)) {
    throw new AgentRuntimeError("invalid_decision", "tool registry must be an array or object");
  }
  const maxTools = positiveLimit(limits.maxTools, L3_MAX_TOOL_PROJECTIONS, "maxTools");
  if (entries.length > maxTools) {
    throw new AgentRuntimeError("tool_limit", "tool registry exceeds the configured count bound");
  }
  const projected = entries.map((entry) => projectToolSpec(entry, limits));
  projected.sort((left, right) => left.name.localeCompare(right.name));
  const names = new Set<string>();
  for (const spec of projected) {
    if (names.has(spec.name)) {
      throw new AgentRuntimeError("tool_limit", `duplicate tool name: ${spec.name}`);
    }
    names.add(spec.name);
  }
  return projected;
}

/** Return a detached tool definition for provider context or test fixtures. */
export function copyToolSpecProjection(spec: ToolSpecProjection): ToolSpecProjection {
  return {
    ...spec,
    gates: [...spec.gates],
    parameters: spec.parameters.map((parameter) => ({ ...parameter })),
    returns: {
      ...spec.returns,
      properties: copyJsonObject(spec.returns.properties),
    },
  };
}

/** Convert a data-only provider tool call into a Rust capability request. */
export function toolInvocationToKernelRequest(
  invocation: ToolInvocationRequest,
  spec: ToolSpecProjection,
): KernelExecutionRequest {
  if (invocation.toolName !== spec.name) {
    throw new AgentRuntimeError("invalid_decision", "tool invocation does not match its registered spec");
  }
  requireText(invocation.callId, "tool call id");
  requireText(invocation.traceId, "tool trace id", true);
  if (!isRecord(invocation.args) || !isJsonValue(invocation.args)) {
    throw new AgentRuntimeError("invalid_decision", "tool invocation args must be a finite JSON object");
  }
  if (jsonBytes(invocation.args) > L3_MAX_TOOL_ARGUMENT_BYTES) {
    throw new AgentRuntimeError("tool_limit", "tool invocation args exceed the byte bound");
  }
  return {
    requestId: invocation.callId,
    authority: "rust",
    operation: RUST_TOOL_INVOKE_OPERATION,
    args: {
      tool_name: spec.name,
      arguments: copyJsonObject(invocation.args),
    },
    ring: ringNumber(spec.ring),
    danger: spec.danger,
    identity: copyAgentIdentity(invocation.identity),
    traceId: invocation.traceId,
  };
}

/** Fold a Rust receipt into a bounded, handler-free tool result value. */
export function toolResultFromReceipt(
  receipt: RustExecutionReceipt,
  invocation: ToolInvocationRequest,
  limits: ToolProjectionLimits = {},
): ToolResultProjection {
  if (receipt.requestId !== invocation.callId) {
    throw new AgentRuntimeError("invalid_receipt", "tool receipt request id does not match the call id");
  }
  if (receipt.traceId !== invocation.traceId) {
    throw new AgentRuntimeError("invalid_receipt", "tool receipt trace id does not match the call");
  }
  if (receipt.data !== undefined && (!isJsonValue(receipt.data) || !isRecord(receipt.data))) {
    throw new AgentRuntimeError("invalid_receipt", "tool receipt data must be a finite JSON object");
  }
  const result: ToolResultProjection = {
    callId: invocation.callId,
    toolName: invocation.toolName,
    receiptId: receipt.receiptId,
    traceId: invocation.traceId,
    success: receipt.accepted,
    status: receipt.accepted ? "completed" : "rejected",
    data: receipt.data ? copyJsonObject(receipt.data) : undefined,
    error: receipt.error,
  };
  const maxResultBytes = positiveLimit(limits.maxResultBytes, L3_MAX_TOOL_RESULT_BYTES, "maxResultBytes");
  if (jsonBytes(result) > maxResultBytes) {
    throw new AgentRuntimeError("tool_result_limit", "tool result exceeds the configured byte bound");
  }
  return result;
}
