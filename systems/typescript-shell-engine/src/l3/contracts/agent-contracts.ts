/**
 * Stable contracts for the TypeScript L3 agent runtime.
 *
 * L3 owns agent coordination and decision flow. Rust remains authoritative
 * for terminal/process admission and hard capability constraints; a kernel
 * action can leave this runtime only through the explicit Rust execution port.
 */

import type { JsonObject, JsonValue } from "../../protocol/wire-records.ts";

/** Version of the TypeScript L3 agent coordination contract. */
export const L3_AGENT_CONTRACT_VERSION = 1 as const;

/** Lifecycle states for one logical agent identity. */
export type AgentRuntimeState = "idle" | "waiting" | "running" | "completed" | "failed" | "stopped";

/** Action kinds a decision provider may return to the runtime. */
export type AgentActionKind = "kernel_request" | "emit";

/** Runtime lifecycle event names emitted to the L2/event projection boundary. */
export type AgentRuntimeEventType =
  | "run_started"
  | "decision_ready"
  | "kernel_request_submitted"
  | "kernel_request_completed"
  | "event_emitted"
  | "run_completed"
  | "run_failed";

/** Stable identity joining the L3 agent to Rust session and terminal truth. */
export interface AgentIdentity {
  readonly agentId: string;
  readonly cellId: string;
  readonly sessionId: string;
  readonly terminalId: string;
}

/** One normalized intent received from the L2 session data layer. */
export interface AgentInput {
  readonly inputId: string;
  readonly inputSeq: number;
  readonly text: string;
  readonly traceId: string;
  readonly identity: AgentIdentity;
  readonly metadata?: JsonObject;
}

/** A Rust-owned capability request produced from a decision action. */
export interface KernelExecutionRequest {
  readonly requestId: string;
  readonly authority: "rust";
  readonly operation: string;
  readonly args: JsonObject;
  readonly ring: number;
  readonly danger: number;
  readonly identity: AgentIdentity;
  readonly traceId: string;
}

/** Receipt returned by the Rust execution adapter after hard-boundary review. */
export interface RustExecutionReceipt {
  readonly receiptId: string;
  readonly requestId: string;
  readonly accepted: boolean;
  readonly status: "accepted" | "completed" | "rejected";
  readonly traceId: string;
  readonly data?: JsonObject;
  readonly error?: string;
}

/** A decision action that must be adjudicated by the Rust kernel. */
export interface KernelRequestAction {
  readonly kind: "kernel_request";
  readonly actionId: string;
  readonly operation: string;
  readonly args: JsonObject;
  readonly ring: number;
  readonly danger: number;
}

/** A decision action that publishes a data-only L3 event. */
export interface EventAction {
  readonly kind: "emit";
  readonly actionId: string;
  readonly eventType: string;
  readonly data: JsonObject;
}

/** Union of actions accepted from an injected decision provider. */
export type AgentAction = KernelRequestAction | EventAction;

/** Provider output for one agent input. */
export interface AgentDecision {
  readonly decisionId: string;
  readonly actions: readonly AgentAction[];
  readonly answer?: string;
}

/** Bounded context supplied to a decision provider. */
export interface AgentDecisionContext {
  readonly identity: AgentIdentity;
  readonly input: AgentInput;
  readonly history: readonly AgentTurnRecord[];
  readonly signal?: AbortSignal;
}

/** Provider-neutral decision function owned by the L3 integration layer. */
export interface AgentDecisionPort {
  /** Produce a bounded data-only plan; no process or tool side effects are implied. */
  decide(input: AgentInput, context: AgentDecisionContext): Promise<AgentDecision>;
}

/** Rust-owned execution authority used for all process/terminal side effects. */
export interface RustKernelExecutionPort {
  readonly authority: "rust";
  /** Submit one request to Rust; rejection is a normal fail-closed receipt. */
  submit(request: KernelExecutionRequest, signal?: AbortSignal): Promise<RustExecutionReceipt>;
}

/** Event sink used to hand L3 lifecycle records to the L2 projection layer. */
export interface AgentEventSink {
  /** Publish one immutable lifecycle event; implementations may be async. */
  publish(event: AgentRuntimeEvent): void | Promise<void>;
}

/** Compact history record exposed to the next decision without retaining payloads. */
export interface AgentTurnRecord {
  readonly inputId: string;
  readonly inputSeq: number;
  readonly traceId: string;
  readonly state: "completed" | "failed" | "stopped";
  readonly actionCount: number;
  readonly answer: string;
}

/** Runtime event carrying only bounded, renderable data. */
export interface AgentRuntimeEvent {
  readonly contractVersion: typeof L3_AGENT_CONTRACT_VERSION;
  readonly eventSeq: number;
  readonly type: AgentRuntimeEventType;
  readonly runId: string;
  readonly traceId: string;
  readonly identity: AgentIdentity;
  readonly data: JsonObject;
  readonly ts: number;
}

/** Public read-only state for one registered agent identity. */
export interface AgentSnapshot {
  readonly identity: AgentIdentity;
  readonly state: AgentRuntimeState;
  readonly activeInputId: string | null;
  readonly acceptedInputs: number;
  readonly nextEventSeq: number;
  readonly history: readonly AgentTurnRecord[];
  readonly lastError?: { readonly code: AgentRuntimeErrorCode; readonly message: string };
}

/** Stable error categories for fail-closed runtime failures. */
export type AgentRuntimeErrorCode =
  | "invalid_input"
  | "invalid_decision"
  | "invalid_receipt"
  | "busy"
  | "cancelled"
  | "decision_timeout"
  | "action_limit"
  | "event_limit"
  | "decision_failed"
  | "execution_failed"
  | "execution_rejected"
  | "event_sink_failed";

/** Structured L3 runtime error that can be projected without parsing text. */
export class AgentRuntimeError extends Error {
  /** Machine-readable failure category. */
  readonly code: AgentRuntimeErrorCode;
  /** Optional bounded context for diagnostics. */
  readonly details?: JsonObject;

  constructor(code: AgentRuntimeErrorCode, message: string, details?: JsonObject) {
    super(message);
    this.name = "AgentRuntimeError";
    this.code = code;
    this.details = details;
  }
}

/** Return a defensive copy of an agent identity. */
export function copyAgentIdentity(identity: AgentIdentity): AgentIdentity {
  return { ...identity };
}

/** Return a defensive copy of a validated JSON value. */
export function copyJsonValue(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map((item) => copyJsonValue(item));
  if (value !== null && typeof value === "object") {
    const result: JsonObject = {};
    for (const [key, item] of Object.entries(value)) result[key] = copyJsonValue(item);
    return result;
  }
  return value;
}

/** Return a defensive copy of a validated JSON object. */
export function copyJsonObject(value: JsonObject): JsonObject {
  return copyJsonValue(value) as JsonObject;
}

/** Return a defensive copy of one admitted L3 input. */
export function copyAgentInput(input: AgentInput): AgentInput {
  return {
    ...input,
    identity: copyAgentIdentity(input.identity),
    metadata: input.metadata ? copyJsonObject(input.metadata) : undefined,
  };
}

/** Return a detached provider context with no caller-owned aliases. */
export function copyAgentDecisionContext(context: AgentDecisionContext): AgentDecisionContext {
  return {
    identity: copyAgentIdentity(context.identity),
    input: copyAgentInput(context.input),
    history: context.history.map((record) => ({ ...record })),
    signal: context.signal,
  };
}
