/**
 * Bounded per-identity AgentLoop for the TypeScript L3 rewrite.
 *
 * The loop is an orchestration primitive, not an execution authority. It
 * serializes one identity's inputs, applies queue backpressure, and delegates
 * every admitted turn to AgentRuntime. Rust remains the only owner of
 * processes, terminals, capabilities, and hard constraints.
 */

import type {
  AgentIdentity,
  AgentInput,
  AgentRuntimeErrorCode,
} from "../contracts/agent-contracts.ts";
import {
  AgentRuntimeError,
  copyAgentIdentity,
  copyAgentInput,
} from "../contracts/agent-contracts.ts";
import type { AgentRunResult, AgentRuntime } from "../runtime/ts-agent-runtime.ts";
import { L3_MAX_PENDING_INPUTS } from "../runtime/limits.ts";

/** Lifecycle of one bounded AgentLoop queue. */
export type AgentLoopState = "accepting" | "draining" | "stopped";

/** Read-only queue and progress view for one full Agent identity. */
export interface AgentLoopSnapshot {
  readonly identity: AgentIdentity;
  readonly state: AgentLoopState;
  readonly activeInputId: string | null;
  readonly queueDepth: number;
  readonly submittedInputs: number;
  readonly completedInputs: number;
  readonly failedInputs: number;
  readonly lastInputSeq: number | null;
  readonly lastError?: {
    readonly code: AgentRuntimeErrorCode;
    readonly message: string;
  };
}

/** Configuration for one per-identity AgentLoop. */
export interface AgentLoopOptions {
  readonly runtime: AgentRuntime;
  readonly maxPendingInputs?: number;
}

interface PendingInput {
  readonly input: AgentInput;
  readonly controller: AbortController;
  readonly disposeSignal: () => void;
  readonly resolve: (result: AgentRunResult) => void;
  readonly reject: (error: AgentRuntimeError) => void;
}

interface LinkedSignal {
  readonly controller: AbortController;
  readonly dispose: () => void;
}

/** Validate the identity fields used for Cell routing. */
export function isAgentIdentity(value: unknown): value is AgentIdentity {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return ["agentId", "cellId", "sessionId", "terminalId"].every((field) => {
    const item = candidate[field];
    return typeof item === "string" && item.length > 0 && !item.includes("\0");
  });
}

/** Stable routing key for the complete Agent identity tuple. */
export function agentIdentityKey(identity: AgentIdentity): string {
  return JSON.stringify([identity.agentId, identity.cellId, identity.sessionId, identity.terminalId]);
}

function linkSignal(signal?: AbortSignal): LinkedSignal {
  const controller = new AbortController();
  if (!signal) return { controller, dispose: () => undefined };
  const onAbort = () => controller.abort(signal.reason);
  if (signal.aborted) controller.abort(signal.reason);
  else signal.addEventListener("abort", onAbort, { once: true });
  return {
    controller,
    dispose: () => signal.removeEventListener("abort", onAbort),
  };
}

function cancelledError(message: string): AgentRuntimeError {
  return new AgentRuntimeError("cancelled", message);
}

function loopError(error: unknown): AgentRuntimeError {
  if (error instanceof AgentRuntimeError) return error;
  return new AgentRuntimeError(
    "execution_failed",
    error instanceof Error ? error.message : "AgentLoop execution failed",
  );
}

/**
 * One FIFO queue bound to `(agentId, cellId, sessionId, terminalId)`.
 *
 * A loop does not clone or reinterpret Rust receipts. AgentRuntime remains the
 * single decision/execution boundary; this class only controls admission and
 * sequencing around it.
 */
export class AgentLoop {
  private readonly key: string;
  private readonly runtime: AgentRuntime;
  private readonly maxPendingInputs: number;
  private readonly queue: PendingInput[] = [];
  private active: PendingInput | null = null;
  private pumping = false;
  private state: AgentLoopState = "accepting";
  private submittedInputs = 0;
  private completedInputs = 0;
  private failedInputs = 0;
  private lastInputSeq: number | null = null;
  private lastError?: { code: AgentRuntimeErrorCode; message: string };
  private drainWaiters: Array<() => void> = [];

  constructor(
    identity: AgentIdentity,
    options: AgentLoopOptions,
  ) {
    if (!isAgentIdentity(identity)) {
      throw new TypeError("AgentLoop identity must contain four non-empty fields");
    }
    this.identity = copyAgentIdentity(identity);
    this.key = agentIdentityKey(identity);
    this.runtime = options.runtime;
    this.maxPendingInputs = options.maxPendingInputs ?? L3_MAX_PENDING_INPUTS;
    if (!Number.isSafeInteger(this.maxPendingInputs) || this.maxPendingInputs < 1) {
      throw new TypeError("maxPendingInputs must be a safe integer >= 1");
    }
  }

  /** Full identity bound to this loop. */
  readonly identity: AgentIdentity;

  /** Submit one input; inputs are processed FIFO and never concurrently. */
  submit(input: AgentInput, signal?: AbortSignal): Promise<AgentRunResult> {
    if (this.state !== "accepting") {
      return Promise.reject(new AgentRuntimeError("loop_stopped", "AgentLoop is no longer accepting inputs"));
    }
    if (!input || typeof input !== "object" || !isAgentIdentity(input.identity) || agentIdentityKey(input.identity) !== this.key) {
      return Promise.reject(new AgentRuntimeError("invalid_input", "AgentLoop input identity does not match its binding"));
    }
    if (!Number.isSafeInteger(input.inputSeq) || input.inputSeq < 0) {
      return Promise.reject(new AgentRuntimeError("invalid_input", "AgentLoop inputSeq must be a non-negative safe integer"));
    }
    if (this.lastInputSeq !== null && input.inputSeq <= this.lastInputSeq) {
      return Promise.reject(new AgentRuntimeError("invalid_input", "AgentLoop inputSeq must increase monotonically"));
    }
    if (this.queue.length >= this.maxPendingInputs) {
      return Promise.reject(new AgentRuntimeError("loop_queue_full", "AgentLoop pending input bound exceeded"));
    }

    const admittedInput = copyAgentInput(input);
    const linked = linkSignal(signal);
    this.lastInputSeq = admittedInput.inputSeq;
    this.submittedInputs += 1;
    return new Promise<AgentRunResult>((resolve, reject) => {
      this.queue.push({
        input: admittedInput,
        controller: linked.controller,
        disposeSignal: linked.dispose,
        resolve,
        reject,
      });
      this.ensurePump();
    });
  }

  /** Stop admission and cancel the active turn plus all queued turns. */
  stop(): void {
    if (this.state === "stopped") return;
    this.state = "stopped";
    this.active?.controller.abort();
    const pending = this.queue.splice(0);
    for (const entry of pending) {
      entry.disposeSignal();
      entry.reject(new AgentRuntimeError("loop_stopped", "AgentLoop stopped before input execution"));
      this.failedInputs += 1;
    }
    this.finishDrainIfIdle();
  }

  /** Stop accepting new work, then resolve after all admitted work settles. */
  async drain(): Promise<void> {
    if (this.state === "accepting") this.state = "draining";
    if (!this.active && this.queue.length === 0) {
      this.state = "stopped";
      return;
    }
    await new Promise<void>((resolve) => this.drainWaiters.push(resolve));
  }

  /** Return a detached, bounded queue snapshot. */
  snapshot(): AgentLoopSnapshot {
    return {
      identity: copyAgentIdentity(this.identity),
      state: this.state,
      activeInputId: this.active?.input.inputId ?? null,
      queueDepth: this.queue.length,
      submittedInputs: this.submittedInputs,
      completedInputs: this.completedInputs,
      failedInputs: this.failedInputs,
      lastInputSeq: this.lastInputSeq,
      lastError: this.lastError ? { ...this.lastError } : undefined,
    };
  }

  private ensurePump(): void {
    if (this.pumping || this.state === "stopped") return;
    this.pumping = true;
    void this.pump();
  }

  private async pump(): Promise<void> {
    try {
      while (this.queue.length > 0 && this.state !== "stopped") {
        const entry = this.queue.shift()!;
        this.active = entry;
        try {
          if (entry.controller.signal.aborted) {
            throw cancelledError("AgentLoop input was cancelled before execution");
          }
          const result = await this.runtime.run(entry.input, entry.controller.signal);
          this.completedInputs += 1;
          this.lastError = undefined;
          entry.resolve(result);
        } catch (error) {
          const runtimeError = loopError(error);
          this.failedInputs += 1;
          this.lastError = { code: runtimeError.code, message: runtimeError.message };
          entry.reject(runtimeError);
        } finally {
          entry.disposeSignal();
          this.active = null;
        }
      }
    } finally {
      this.pumping = false;
      this.finishDrainIfIdle();
      if (this.queue.length > 0 && this.state !== "stopped") this.ensurePump();
    }
  }

  private finishDrainIfIdle(): void {
    if (this.active || this.queue.length > 0) return;
    if (this.state === "draining") this.state = "stopped";
    if (this.state !== "stopped" && this.drainWaiters.length === 0) return;
    const waiters = this.drainWaiters.splice(0);
    for (const resolve of waiters) resolve();
  }
}

/** Construct a cancellation error for callers that need a stable type guard. */
export function agentLoopCancellation(message = "AgentLoop input was cancelled"): AgentRuntimeError {
  return cancelledError(message);
}
