/**
 * Bounded defaults for the TypeScript L3 runtime.
 *
 * These are coordination limits, not Rust authorization policy. Ring/danger
 * values remain explicit inputs and are adjudicated by the Rust port.
 */

/** Maximum UTF-8 bytes in one L2-to-L3 intent. */
export const L3_MAX_INPUT_BYTES = 64 * 1024;
/** Maximum decision actions admitted for one intent. */
export const L3_MAX_ACTIONS_PER_INPUT = 64;
/** Maximum prior turn summaries retained per agent identity. */
export const L3_MAX_HISTORY_ENTRIES = 128;
/** Maximum serialized event data bytes emitted by one action. */
export const L3_MAX_EVENT_DATA_BYTES = 16 * 1024;
/** Maximum queued (not currently executing) inputs for one AgentLoop. */
export const L3_MAX_PENDING_INPUTS = 32;
/** Maximum retained lifecycle events per identity in the in-memory replay ledger. */
export const L3_MAX_REPLAY_EVENTS = 256;
/** Maximum Rust sessions, terminals, and loops accepted by one projection parse. */
export const L3_MAX_RUST_PROJECTION_ENTITIES = 4096;
/** Maximum Cell registrations held by one TypeScript L3B router. */
export const L3_MAX_REGISTERED_CELLS = 256;
/** Maximum number of cross-Cell forwarding hops admitted for one route. */
export const L3_MAX_CROSS_CELL_HOPS = 8;
/** Maximum UTF-8 bytes in a cross-Cell route identifier. */
export const L3_MAX_ROUTE_ID_BYTES = 128;
/** Maximum UTF-8 bytes in optional cross-Cell route metadata. */
export const L3_MAX_ROUTE_METADATA_BYTES = 8 * 1024;

/** Tunable runtime bounds accepted by the coordinator. */
export interface AgentRuntimeLimits {
  readonly maxInputBytes: number;
  readonly maxActionsPerInput: number;
  readonly maxHistoryEntries: number;
  readonly maxEventDataBytes: number;
}

/** Default bounded runtime configuration. */
export const DEFAULT_AGENT_RUNTIME_LIMITS: AgentRuntimeLimits = {
  maxInputBytes: L3_MAX_INPUT_BYTES,
  maxActionsPerInput: L3_MAX_ACTIONS_PER_INPUT,
  maxHistoryEntries: L3_MAX_HISTORY_ENTRIES,
  maxEventDataBytes: L3_MAX_EVENT_DATA_BYTES,
};

/** Merge and validate caller-provided coordination bounds. */
export function resolveAgentRuntimeLimits(
  overrides: Partial<AgentRuntimeLimits> = {},
): AgentRuntimeLimits {
  const resolved = { ...DEFAULT_AGENT_RUNTIME_LIMITS, ...overrides };
  for (const [name, value] of Object.entries(resolved)) {
    if (!Number.isSafeInteger(value) || value < 1) {
      throw new Error(`${name} must be a positive safe integer`);
    }
  }
  return resolved;
}
