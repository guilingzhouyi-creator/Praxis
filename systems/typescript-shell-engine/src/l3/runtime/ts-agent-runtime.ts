/**
 * Bounded TypeScript L3 agent coordinator.
 *
 * This is a clean-break orchestration core, not a line-by-line translation of
 * Python's AgentLoop. It owns per-agent turn state, decision sequencing,
 * bounded history, and lifecycle events. Rust remains the only side-effecting
 * execution authority: process, terminal, capability, and hard-constraint
 * work crosses the explicit RustKernelExecutionPort.
 */

import type {
  AgentAction,
  AgentDecision,
  AgentDecisionContext,
  AgentEventSink,
  AgentIdentity,
  AgentInput,
  AgentRuntimeErrorCode,
  AgentRuntimeEvent,
  AgentRuntimeState,
  AgentSnapshot,
  AgentTurnRecord,
  EventAction,
  KernelExecutionRequest,
  RustExecutionReceipt,
  RustKernelExecutionPort,
} from "../contracts/agent-contracts.ts";
import {
  AgentRuntimeError,
  L3_AGENT_CONTRACT_VERSION,
  copyAgentIdentity,
  copyAgentInput,
  copyJsonObject,
} from "../contracts/agent-contracts.ts";
import type { JsonObject, JsonValue } from "../../protocol/wire-records.ts";
import {
  DEFAULT_AGENT_RUNTIME_LIMITS,
  resolveAgentRuntimeLimits,
  type AgentRuntimeLimits,
} from "./limits.ts";

/** Decision/execution/event dependencies for one coordinator instance. */
export interface AgentRuntimeOptions {
  readonly decision: {
    decide(input: AgentInput, context: AgentDecisionContext): Promise<AgentDecision>;
  };
  readonly execution: RustKernelExecutionPort;
  readonly events?: AgentEventSink;
  readonly limits?: Partial<AgentRuntimeLimits>;
  readonly clock?: () => number;
}

/** Result of one completed agent turn. */
export interface AgentRunResult {
  readonly contractVersion: typeof L3_AGENT_CONTRACT_VERSION;
  readonly runId: string;
  readonly identity: AgentIdentity;
  readonly state: "completed";
  readonly answer: string;
  readonly actions: number;
  readonly receipts: readonly RustExecutionReceipt[];
}

interface MutableAgentState {
  readonly identity: AgentIdentity;
  state: AgentRuntimeState;
  activeInputId: string | null;
  acceptedInputs: number;
  nextEventSeq: number;
  history: AgentTurnRecord[];
  lastError?: { code: AgentRuntimeErrorCode; message: string };
}

const EMPTY_EVENTS: AgentEventSink = {
  publish: () => undefined,
};

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function jsonBytes(value: object): number {
  return utf8Bytes(JSON.stringify(value));
}

function identityKey(identity: AgentIdentity): string {
  return JSON.stringify([identity.agentId, identity.cellId, identity.sessionId, identity.terminalId]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown, ancestors: WeakSet<object> = new WeakSet<object>()): value is JsonValue {
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

function validateJsonObject(
  value: unknown,
  name: string,
  code: AgentRuntimeErrorCode = "invalid_decision",
): asserts value is JsonObject {
  if (!isRecord(value) || !isJsonValue(value)) {
    throw new AgentRuntimeError(code, `${name} must be a finite JSON object`);
  }
}

function requireText(value: unknown, name: string): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new AgentRuntimeError("invalid_input", `${name} must be a non-empty string`);
  }
}

function validateIdentity(value: unknown): asserts value is AgentIdentity {
  if (!isRecord(value)) {
    throw new AgentRuntimeError("invalid_input", "identity must be an object");
  }
  requireText(value.agentId, "identity.agentId");
  requireText(value.cellId, "identity.cellId");
  requireText(value.sessionId, "identity.sessionId");
  requireText(value.terminalId, "identity.terminalId");
  const identifiers: readonly [string, string][] = [
    ["agentId", value.agentId as string],
    ["cellId", value.cellId as string],
    ["sessionId", value.sessionId as string],
    ["terminalId", value.terminalId as string],
  ];
  for (const [name, identifier] of identifiers) {
    if (identifier.includes("\0")) {
      throw new AgentRuntimeError("invalid_input", `${name} cannot contain NUL`);
    }
  }
}

function asRuntimeError(error: unknown, code: AgentRuntimeErrorCode, fallback: string): AgentRuntimeError {
  if (error instanceof AgentRuntimeError) return error;
  return new AgentRuntimeError(code, error instanceof Error ? error.message : fallback);
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new AgentRuntimeError("cancelled", "agent input was cancelled");
}

function validateInput(input: AgentInput, limits: AgentRuntimeLimits): void {
  if (!isRecord(input)) {
    throw new AgentRuntimeError("invalid_input", "agent input must be an object");
  }
  requireText(input.inputId, "inputId");
  requireText(input.text, "text");
  validateIdentity(input.identity);
  if (!Number.isSafeInteger(input.inputSeq) || input.inputSeq < 0) {
    throw new AgentRuntimeError("invalid_input", "inputSeq must be a non-negative safe integer");
  }
  if (typeof input.traceId !== "string") {
    throw new AgentRuntimeError("invalid_input", "traceId must be a string");
  }
  if (input.metadata !== undefined) validateJsonObject(input.metadata, "input metadata", "invalid_input");
  if (utf8Bytes(input.text) > limits.maxInputBytes) {
    throw new AgentRuntimeError("invalid_input", "agent input exceeds the configured byte bound");
  }
}

function validateAction(action: AgentAction, seen: Set<string>): void {
  if (!isRecord(action)) {
    throw new AgentRuntimeError("invalid_decision", "agent action must be an object");
  }
  requireText(action.actionId, "actionId");
  if (seen.has(action.actionId)) {
    throw new AgentRuntimeError("invalid_decision", `duplicate action id: ${action.actionId}`);
  }
  seen.add(action.actionId);
  if (action.kind === "kernel_request") {
    requireText(action.operation, "operation");
    validateJsonObject(action.args, "kernel request args");
    if (!Number.isSafeInteger(action.ring) || action.ring < 0) {
      throw new AgentRuntimeError("invalid_decision", "kernel request ring must be a non-negative safe integer");
    }
    if (!Number.isSafeInteger(action.danger) || action.danger < 0) {
      throw new AgentRuntimeError("invalid_decision", "kernel request danger must be a non-negative safe integer");
    }
    return;
  }
  if (action.kind === "emit") {
    requireText(action.eventType, "eventType");
    validateJsonObject(action.data, "event action data");
    return;
  }
  throw new AgentRuntimeError("invalid_decision", "unknown agent action kind");
}

function validateDecision(decision: AgentDecision, maxActions: number): void {
  if (!isRecord(decision)) {
    throw new AgentRuntimeError("invalid_decision", "agent decision must be an object");
  }
  requireText(decision.decisionId, "decisionId");
  if (!Array.isArray(decision.actions)) {
    throw new AgentRuntimeError("invalid_decision", "decision actions must be an array");
  }
  if (decision.actions.length > maxActions) {
    throw new AgentRuntimeError("action_limit", "decision exceeds the action bound");
  }
  if (decision.answer !== undefined && typeof decision.answer !== "string") {
    throw new AgentRuntimeError("invalid_decision", "decision answer must be a string");
  }
  const seen = new Set<string>();
  for (const action of decision.actions) validateAction(action, seen);
}

function validateReceipt(receipt: RustExecutionReceipt, request: KernelExecutionRequest): void {
  if (!isRecord(receipt)) {
    throw new AgentRuntimeError("invalid_receipt", "Rust execution receipt must be an object");
  }
  requireText(receipt.receiptId, "receiptId");
  if (typeof receipt.requestId !== "string" || typeof receipt.traceId !== "string") {
    throw new AgentRuntimeError("invalid_receipt", "Rust receipt identifiers must be strings");
  }
  if (receipt.requestId !== request.requestId) {
    throw new AgentRuntimeError("invalid_receipt", "Rust receipt request id does not match the submitted action");
  }
  if (receipt.traceId !== request.traceId) {
    throw new AgentRuntimeError("invalid_receipt", "Rust receipt trace id does not match the submitted action");
  }
  if (receipt.accepted && receipt.status === "rejected") {
    throw new AgentRuntimeError("invalid_receipt", "Rust receipt cannot be accepted and rejected");
  }
  if (!receipt.accepted && receipt.status !== "rejected") {
    throw new AgentRuntimeError("invalid_receipt", "Rust denial must use rejected status");
  }
  if (receipt.status === "rejected" && (!receipt.error || receipt.error.length === 0)) {
    throw new AgentRuntimeError("invalid_receipt", "Rust rejection must include an error");
  }
  if (receipt.data !== undefined) validateJsonObject(receipt.data, "Rust receipt data", "invalid_receipt");
}

/** L3 coordinator for many independent AgentLoop identities. */
export class AgentRuntime {
  private readonly agents = new Map<string, MutableAgentState>();
  private readonly events: AgentEventSink;
  private readonly limits: AgentRuntimeLimits;
  private readonly clock: () => number;

  constructor(
    private readonly options: AgentRuntimeOptions,
  ) {
    if (options.execution.authority !== "rust") {
      throw new AgentRuntimeError("execution_failed", "L3 execution authority must be Rust");
    }
    this.events = options.events ?? EMPTY_EVENTS;
    this.limits = resolveAgentRuntimeLimits(options.limits);
    this.clock = options.clock ?? (() => Date.now() / 1000);
  }

  /** Return a defensive snapshot for one identity, or null when unregistered. */
  snapshot(identity: AgentIdentity): AgentSnapshot | null {
    if (!isRecord(identity)) return null;
    try {
      validateIdentity(identity);
    } catch {
      return null;
    }
    const state = this.agents.get(identityKey(identity));
    if (!state) return null;
    return {
      identity: copyAgentIdentity(state.identity),
      state: state.state,
      activeInputId: state.activeInputId,
      acceptedInputs: state.acceptedInputs,
      nextEventSeq: state.nextEventSeq,
      history: state.history.map((record) => ({ ...record })),
      lastError: state.lastError ? { ...state.lastError } : undefined,
    };
  }

  /** Return snapshots in deterministic identity order. */
  snapshots(): AgentSnapshot[] {
    return [...this.agents.values()]
      .sort((left, right) => identityKey(left.identity).localeCompare(identityKey(right.identity)))
      .map((state) => this.snapshot(state.identity)!)
      ;
  }

  /** Run one bounded intent through decision, Rust admission, and event projection. */
  async run(input: AgentInput, signal?: AbortSignal): Promise<AgentRunResult> {
    validateInput(input, this.limits);
    throwIfAborted(signal);
    // Admit a detached value before invoking provider code. The provider is
    // untrusted coordination logic; passing the caller-owned input directly
    // would let it mutate the identity/text used for the Rust request or
    // history after validation.
    const admittedInput = copyAgentInput(input);
    const state = this.getOrCreate(admittedInput.identity);
    if (state.activeInputId !== null || state.state === "waiting" || state.state === "running") {
      throw new AgentRuntimeError("busy", `agent ${admittedInput.identity.agentId} already has an active input`);
    }
    if (state.history.some((record) => record.inputId === admittedInput.inputId)) {
      throw new AgentRuntimeError("invalid_input", `input id already processed: ${admittedInput.inputId}`);
    }

    state.activeInputId = admittedInput.inputId;
    state.state = "waiting";
    state.lastError = undefined;
    const receipts: RustExecutionReceipt[] = [];
    let actionCount = 0;

    try {
      await this.emit(state, admittedInput, "run_started", { input_seq: admittedInput.inputSeq });
      const context: AgentDecisionContext = {
        identity: copyAgentIdentity(admittedInput.identity),
        input: copyAgentInput(admittedInput),
        history: state.history.map((record) => ({ ...record })),
        signal,
      };
      let decision: AgentDecision;
      try {
        decision = await this.options.decision.decide(copyAgentInput(admittedInput), context);
      } catch (error) {
        throw asRuntimeError(error, "decision_failed", "agent decision failed");
      }
      validateDecision(decision, this.limits.maxActionsPerInput);
      state.state = "running";
      await this.emit(state, admittedInput, "decision_ready", {
        decision_id: decision.decisionId,
        action_count: decision.actions.length,
      });

      for (const action of decision.actions) {
        throwIfAborted(signal);
        actionCount += 1;
        if (action.kind === "kernel_request") {
          const request: KernelExecutionRequest = {
            requestId: action.actionId,
            authority: "rust",
            operation: action.operation,
            args: copyJsonObject(action.args),
            ring: action.ring,
            danger: action.danger,
            identity: copyAgentIdentity(admittedInput.identity),
            traceId: admittedInput.traceId,
          };
          await this.emit(state, admittedInput, "kernel_request_submitted", {
            request_id: request.requestId,
            operation: request.operation,
          });
          let receipt: RustExecutionReceipt;
          try {
            receipt = await this.options.execution.submit(request, signal);
          } catch (error) {
            throw asRuntimeError(error, "execution_failed", "Rust execution failed");
          }
          validateReceipt(receipt, request);
          receipts.push({ ...receipt, data: receipt.data ? { ...receipt.data } : undefined });
          await this.emit(state, admittedInput, "kernel_request_completed", {
            request_id: request.requestId,
            receipt_id: receipt.receiptId,
            status: receipt.status,
            accepted: receipt.accepted,
          });
          if (!receipt.accepted) {
            throw new AgentRuntimeError("execution_rejected", receipt.error ?? "Rust rejected the request");
          }
        } else {
          await this.emitEventAction(state, admittedInput, action);
        }
      }

      const answer = decision.answer ?? "";
      state.state = "completed";
      state.activeInputId = null;
      state.acceptedInputs += 1;
      this.recordHistory(state, {
        inputId: admittedInput.inputId,
        inputSeq: admittedInput.inputSeq,
        traceId: admittedInput.traceId,
        state: "completed",
        actionCount,
        answer,
      });
      await this.emit(state, admittedInput, "run_completed", { action_count: actionCount });
      return {
        contractVersion: L3_AGENT_CONTRACT_VERSION,
        runId: admittedInput.inputId,
        identity: copyAgentIdentity(admittedInput.identity),
        state: "completed",
        answer,
        actions: actionCount,
        receipts,
      };
    } catch (error) {
      const runtimeError = asRuntimeError(error, "execution_failed", "agent runtime failed");
      state.state = runtimeError.code === "cancelled" ? "stopped" : "failed";
      state.activeInputId = null;
      state.lastError = { code: runtimeError.code, message: runtimeError.message };
      this.recordHistory(state, {
        inputId: admittedInput.inputId,
        inputSeq: admittedInput.inputSeq,
        traceId: admittedInput.traceId,
        state: state.state,
        actionCount,
        answer: "",
      });
      await this.emitFailure(state, admittedInput, runtimeError);
      throw runtimeError;
    }
  }

  private getOrCreate(identity: AgentIdentity): MutableAgentState {
    const key = identityKey(identity);
    const existing = this.agents.get(key);
    if (existing) return existing;
    const state: MutableAgentState = {
      identity: copyAgentIdentity(identity),
      state: "idle",
      activeInputId: null,
      acceptedInputs: 0,
      nextEventSeq: 1,
      history: [],
    };
    this.agents.set(key, state);
    return state;
  }

  private recordHistory(state: MutableAgentState, record: AgentTurnRecord): void {
    state.history.push(record);
    if (state.history.length > this.limits.maxHistoryEntries) {
      state.history.splice(0, state.history.length - this.limits.maxHistoryEntries);
    }
  }

  private async emit(
    state: MutableAgentState,
    input: AgentInput,
    type: AgentRuntimeEvent["type"],
    data: JsonObject,
  ): Promise<void> {
    if (jsonBytes(data) > this.limits.maxEventDataBytes) {
      throw new AgentRuntimeError("event_limit", "agent event exceeds the configured byte bound");
    }
    const event: AgentRuntimeEvent = {
      contractVersion: L3_AGENT_CONTRACT_VERSION,
      eventSeq: state.nextEventSeq++,
      type,
      runId: input.inputId,
      traceId: input.traceId,
      identity: copyAgentIdentity(input.identity),
      data: copyJsonObject(data),
      ts: this.clock(),
    };
    try {
      await this.events.publish(event);
    } catch (error) {
      throw asRuntimeError(error, "event_sink_failed", "agent event sink failed");
    }
  }

  private async emitEventAction(state: MutableAgentState, input: AgentInput, action: EventAction): Promise<void> {
    if (jsonBytes(action.data) > this.limits.maxEventDataBytes) {
      throw new AgentRuntimeError("event_limit", "agent event action exceeds the configured byte bound");
    }
    await this.emit(state, input, "event_emitted", {
      action_id: action.actionId,
      event_type: action.eventType,
      data: copyJsonObject(action.data),
    });
  }

  private async emitFailure(
    state: MutableAgentState,
    input: AgentInput,
    error: AgentRuntimeError,
  ): Promise<void> {
    try {
      await this.emit(state, input, "run_failed", {
        code: error.code,
        message: error.message,
      });
    } catch {
      // A failed sink cannot recursively become another runtime failure.
    }
  }
}
