/**
 * L3A peer routing over the TypeScript AgentCell candidate.
 *
 * This router binds a logical L3A peer to one complete Agent identity and
 * delegates turns to AgentCell. It owns no session store, process handle,
 * terminal, PTY, capability, or Rust implementation.
 */

import type { AgentIdentity, AgentInput } from "../contracts/agent-contracts.ts";
import { AgentRuntimeError, copyAgentIdentity } from "../contracts/agent-contracts.ts";
import type { AgentRunResult, AgentRuntime } from "../runtime/ts-agent-runtime.ts";
import { AgentCell } from "../cell/agent-cell.ts";
import { agentIdentityKey, isAgentIdentity } from "../loop/agent-loop-queue.ts";

/** Lifecycle of one L3A peer binding. */
export type L3APeerState = "attached" | "detached";

/** Detached identity binding exposed to L2/L3A projections. */
export interface L3APeerBinding {
  readonly peerId: string;
  readonly identity: AgentIdentity;
  readonly state: L3APeerState;
}

/** Construction options for one Cell-local peer router. */
export interface L3APeerRouterOptions {
  readonly runtime: AgentRuntime;
  readonly maxPendingInputs?: number;
}

interface MutablePeerBinding {
  readonly peerId: string;
  readonly identity: AgentIdentity;
  state: L3APeerState;
}

function requirePeerId(peerId: unknown): asserts peerId is string {
  if (typeof peerId !== "string" || peerId.length === 0 || peerId.includes("\0")) {
    throw new AgentRuntimeError("invalid_input", "peerId must be a non-empty string");
  }
}

function requireIdentity(identity: unknown): asserts identity is AgentIdentity {
  if (!isAgentIdentity(identity)) {
    throw new AgentRuntimeError("invalid_input", "peer identity must contain four non-empty fields");
  }
}

function copyBinding(binding: MutablePeerBinding): L3APeerBinding {
  return {
    peerId: binding.peerId,
    identity: copyAgentIdentity(binding.identity),
    state: binding.state,
  };
}

/**
 * Routes L3A peer inputs to one AgentCell without leaking loop handles.
 *
 * One identity can have at most one attached peer in this router. Detached
 * peer IDs remain as tombstones so stale callers receive a deterministic
 * `peer_detached` error rather than being mistaken for a new route.
 */
export class L3APeerRouter {
  private readonly cell: AgentCell;
  private readonly peers = new Map<string, MutablePeerBinding>();
  private readonly identities = new Map<string, string>();

  constructor(options: L3APeerRouterOptions) {
    this.cell = new AgentCell({
      runtime: options.runtime,
      maxPendingInputs: options.maxPendingInputs,
    });
  }

  /** Attach or reattach one peer to a unique full identity. */
  attach(peerId: string, identity: AgentIdentity): L3APeerBinding {
    requirePeerId(peerId);
    requireIdentity(identity);
    const existing = this.peers.get(peerId);
    if (existing?.state === "attached") {
      throw new AgentRuntimeError("peer_conflict", `peer is already attached: ${peerId}`);
    }
    const identityKey = agentIdentityKey(identity);
    const owner = this.identities.get(identityKey);
    if (owner !== undefined && owner !== peerId) {
      throw new AgentRuntimeError("peer_conflict", `identity is already bound to peer: ${owner}`);
    }
    const binding: MutablePeerBinding = {
      peerId,
      identity: copyAgentIdentity(identity),
      state: "attached",
    };
    this.peers.set(peerId, binding);
    this.identities.set(identityKey, peerId);
    return copyBinding(binding);
  }

  /** Submit by identity, enforcing that an attached peer owns the route. */
  submit(input: AgentInput, signal?: AbortSignal): Promise<AgentRunResult> {
    if (!input || typeof input !== "object" || !isAgentIdentity(input.identity)) {
      return Promise.reject(new AgentRuntimeError("invalid_input", "peer input must contain a valid identity"));
    }
    const peerId = this.identities.get(agentIdentityKey(input.identity));
    if (peerId === undefined) {
      return Promise.reject(new AgentRuntimeError("peer_not_found", "no attached peer owns the input identity"));
    }
    return this.submitTo(peerId, input, signal);
  }

  /** Submit through an explicit peer ID and reject identity spoofing. */
  submitTo(peerId: string, input: AgentInput, signal?: AbortSignal): Promise<AgentRunResult> {
    requirePeerId(peerId);
    const binding = this.peers.get(peerId);
    if (!binding) {
      return Promise.reject(new AgentRuntimeError("peer_not_found", `unknown peer: ${peerId}`));
    }
    if (binding.state !== "attached") {
      return Promise.reject(new AgentRuntimeError("peer_detached", `peer is detached: ${peerId}`));
    }
    if (!input || typeof input !== "object" || !isAgentIdentity(input.identity)) {
      return Promise.reject(new AgentRuntimeError("invalid_input", "peer input must contain a valid identity"));
    }
    if (agentIdentityKey(input.identity) !== agentIdentityKey(binding.identity)) {
      return Promise.reject(new AgentRuntimeError("peer_conflict", "peer input identity does not match its binding"));
    }
    return this.cell.submit(input, signal);
  }

  /** Return one detached peer binding, or null when the ID is unknown. */
  binding(peerId: string): L3APeerBinding | null {
    requirePeerId(peerId);
    const binding = this.peers.get(peerId);
    return binding ? copyBinding(binding) : null;
  }

  /** Return all peer bindings in deterministic peer-ID order. */
  bindings(): L3APeerBinding[] {
    return [...this.peers.values()]
      .sort((left, right) => left.peerId.localeCompare(right.peerId))
      .map(copyBinding);
  }

  /** Detach one peer, optionally stopping its AgentLoop admission. */
  detach(peerId: string, options: { readonly stop?: boolean } = {}): void {
    requirePeerId(peerId);
    const binding = this.peers.get(peerId);
    if (!binding) throw new AgentRuntimeError("peer_not_found", `unknown peer: ${peerId}`);
    if (binding.state === "detached") return;
    binding.state = "detached";
    this.identities.delete(agentIdentityKey(binding.identity));
    if (options.stop) this.cell.stop(binding.identity);
  }

  /** Drain one peer's admitted inputs and then detach it. */
  async drain(peerId: string): Promise<void> {
    requirePeerId(peerId);
    const binding = this.peers.get(peerId);
    if (!binding) throw new AgentRuntimeError("peer_not_found", `unknown peer: ${peerId}`);
    if (binding.state === "detached") return;
    await this.cell.loop(binding.identity).drain();
    this.detach(peerId);
  }

  /** Drain every attached peer and resolve after all admitted work settles. */
  async drainAll(): Promise<void> {
    await Promise.all(
      this.bindings()
        .filter((binding) => binding.state === "attached")
        .map((binding) => this.drain(binding.peerId)),
    );
  }
}
