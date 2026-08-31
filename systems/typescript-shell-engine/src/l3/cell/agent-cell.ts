/**
 * Cell-level routing for independent TypeScript L3 AgentLoops.
 *
 * A Cell owns no Rust process, terminal, capability, or durable-session state.
 * It only resolves the full Agent identity to a bounded FIFO AgentLoop and
 * delegates execution to the injected AgentRuntime.
 */

import type { AgentIdentity, AgentInput } from "../contracts/agent-contracts.ts";
import { AgentRuntimeError, copyAgentIdentity } from "../contracts/agent-contracts.ts";
import type { AgentRunResult, AgentRuntime } from "../runtime/ts-agent-runtime.ts";
import {
  AgentLoop,
  agentIdentityKey,
  isAgentIdentity,
  type AgentLoopOptions,
  type AgentLoopSnapshot,
} from "../loop/agent-loop-queue.ts";

/** Options for one L3 Cell coordinator. */
export interface AgentCellOptions {
  readonly runtime: AgentRuntime;
  readonly maxPendingInputs?: number;
}

/**
 * Routes inputs to per-identity AgentLoops inside one logical Cell.
 *
 * Inputs for one identity remain FIFO; different identities can progress in
 * parallel because the underlying AgentRuntime also keys state by the full
 * identity tuple.
 */
export class AgentCell {
  private readonly loops = new Map<string, AgentLoop>();
  private readonly runtime: AgentRuntime;
  private readonly loopOptions: Omit<AgentLoopOptions, "runtime">;

  constructor(options: AgentCellOptions) {
    this.runtime = options.runtime;
    this.loopOptions = { maxPendingInputs: options.maxPendingInputs };
  }

  /** Resolve or lazily construct the loop for a full Agent identity. */
  loop(identity: AgentIdentity): AgentLoop {
    if (!isAgentIdentity(identity)) {
      throw new AgentRuntimeError("invalid_input", "Cell identity must contain four non-empty fields");
    }
    const key = agentIdentityKey(identity);
    const existing = this.loops.get(key);
    if (existing) return existing;
    const loop = new AgentLoop(copyAgentIdentity(identity), {
      runtime: this.runtime,
      ...this.loopOptions,
    });
    this.loops.set(key, loop);
    return loop;
  }

  /** Route one normalized L2 input to its identity-bound AgentLoop. */
  submit(input: AgentInput, signal?: AbortSignal): Promise<AgentRunResult> {
    if (!input || typeof input !== "object" || !isAgentIdentity(input.identity)) {
      return Promise.reject(new AgentRuntimeError("invalid_input", "Cell input must contain a valid Agent identity"));
    }
    return this.loop(input.identity).submit(input, signal);
  }

  /** Return one loop snapshot, or null when the Cell has not seen the identity. */
  snapshot(identity: AgentIdentity): AgentLoopSnapshot | null {
    if (!isAgentIdentity(identity)) return null;
    return this.loops.get(agentIdentityKey(identity))?.snapshot() ?? null;
  }

  /** Return loop snapshots in deterministic full-identity order. */
  snapshots(): AgentLoopSnapshot[] {
    return [...this.loops.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([, loop]) => loop.snapshot());
  }

  /** Stop one identity without affecting sibling AgentLoops. */
  stop(identity: AgentIdentity): void {
    if (!isAgentIdentity(identity)) return;
    this.loops.get(agentIdentityKey(identity))?.stop();
  }

  /** Drain all loops and resolve when every admitted input has settled. */
  async drain(): Promise<void> {
    await Promise.all([...this.loops.values()].map((loop) => loop.drain()));
  }
}
