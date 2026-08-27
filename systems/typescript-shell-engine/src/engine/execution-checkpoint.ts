/**
 * Read-only TypeScript view of the Rust execution checkpoint.
 *
 * The Rust kernel remains authoritative for live SessionBook, TerminalBook,
 * and AgentLoopBook state. This adapter validates a durable document for
 * projection and recovery UI; it never mutates the Rust root or executes work.
 */

import { readFile, stat } from "node:fs/promises";
import path from "node:path";

import { canonicalJson } from "../wire-records.ts";
import {
  SESSION_STORE_VERSION,
  type RustSessionCheckpoint,
  validateSessionStoreDocument,
} from "./session-checkpoint.ts";

/** Rust execution checkpoint schema version. */
export const EXECUTION_STORE_VERSION = 1 as const;
/** Rust logical AgentLoop contract version. */
export const AGENT_LOOP_CONTRACT_VERSION = 1 as const;
/** Maximum UTF-8 identity length accepted by the AgentLoop contract. */
export const AGENT_LOOP_MAX_ID_BYTES = 128 as const;
/** Rust-owned relative execution checkpoint path below a state root. */
export const EXECUTION_STORE_RELATIVE_PATH = "snapshots/execution/checkpoint.json" as const;

export type RustTerminalState = "created" | "ready" | "running" | "stopped" | "closed";
export type RustAgentLoopState = "created" | "ready" | "running" | "paused" | "closing" | "stopped" | "failed";

/** Metadata-only Rust terminal snapshot. */
export interface RustTerminalSnapshot {
  terminal_id: string;
  state: RustTerminalState;
  session_id: string | null;
  process_id: number | null;
  input_capacity: number;
  output_capacity: number;
  input_depth: number;
  output_depth: number;
  input_dropped: number;
  output_dropped: number;
}

/** Declarative identity for one logical Rust AgentLoop. */
export interface RustAgentLoopSpec {
  loop_id: string;
  agent_id: string;
  cell_id: string;
  session_id: string;
  terminal_id: string;
}

/** Metadata-only Rust AgentLoop snapshot. */
export interface RustAgentLoopSnapshot {
  contract_version: typeof AGENT_LOOP_CONTRACT_VERSION;
  spec: RustAgentLoopSpec;
  state: RustAgentLoopState;
  next_command_seq: number;
  accepted_commands: number;
  failed_commands: number;
  lock_wait_ns: number;
}

/** Combined Rust execution checkpoint consumed by TS projections. */
export interface RustExecutionStoreDocument {
  store_version: typeof EXECUTION_STORE_VERSION;
  generation: number;
  clean_shutdown: boolean;
  sessions: RustSessionCheckpoint[];
  terminals: RustTerminalSnapshot[];
  loops: RustAgentLoopSnapshot[];
}

/** Fail-closed error at the TS execution checkpoint boundary. */
export class ExecutionCheckpointError extends Error {
  /** Describe one rejected execution checkpoint. */
  constructor(message: string) {
    super(message);
    this.name = "ExecutionCheckpointError";
  }
}

const TERMINAL_STATES: readonly RustTerminalState[] = ["created", "ready", "running", "stopped", "closed"];
const LOOP_STATES: readonly RustAgentLoopState[] = ["created", "ready", "running", "paused", "closing", "stopped", "failed"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, name: string): Record<string, unknown> {
  if (!isRecord(value)) throw new ExecutionCheckpointError(`${name} must be an object`);
  return value;
}

function textBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function requireIdentity(value: unknown, name: string, maxBytes?: number): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.includes("\0")) {
    throw new ExecutionCheckpointError(`${name} must be a non-empty identity`);
  }
  if (maxBytes !== undefined && textBytes(value) > maxBytes) {
    throw new ExecutionCheckpointError(`${name} exceeds ${maxBytes} bytes`);
  }
  return value;
}

function requireSafeUint(value: unknown, name: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    throw new ExecutionCheckpointError(`${name} must be a safe integer >= ${minimum}`);
  }
  return value;
}

function requireBoolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") throw new ExecutionCheckpointError(`${name} must be a boolean`);
  return value;
}

function optionalSafeUint(value: unknown, name: string): number | null {
  if (value === null) return null;
  return requireSafeUint(value, name, 1);
}

function sortedUnique<T extends string>(values: readonly T[], name: string): void {
  let previous: string | undefined;
  for (const value of values) {
    if (previous !== undefined && previous >= value) {
      throw new ExecutionCheckpointError(`${name} must be sorted and unique`);
    }
    previous = value;
  }
}

function parseTerminal(value: unknown): RustTerminalSnapshot {
  const raw = requireRecord(value, "terminal snapshot");
  const state = raw.state;
  if (typeof state !== "string" || !(TERMINAL_STATES as readonly string[]).includes(state)) {
    throw new ExecutionCheckpointError(`unknown terminal state: ${String(state)}`);
  }
  const inputCapacity = requireSafeUint(raw.input_capacity, "terminal input_capacity", 1);
  const outputCapacity = requireSafeUint(raw.output_capacity, "terminal output_capacity", 1);
  const inputDepth = requireSafeUint(raw.input_depth, "terminal input_depth");
  const outputDepth = requireSafeUint(raw.output_depth, "terminal output_depth");
  const sessionId = raw.session_id === null ? null : requireIdentity(raw.session_id, "terminal session_id");
  const processId = optionalSafeUint(raw.process_id, "terminal process_id");
  if (state === "closed" && sessionId !== null) {
    throw new ExecutionCheckpointError("closed terminal cannot retain a session binding");
  }
  return {
    terminal_id: requireIdentity(raw.terminal_id, "terminal_id"),
    state: state as RustTerminalState,
    session_id: sessionId,
    process_id: processId,
    input_capacity: inputCapacity,
    output_capacity: outputCapacity,
    input_depth: inputDepth,
    output_depth: outputDepth,
    input_dropped: requireSafeUint(raw.input_dropped, "terminal input_dropped"),
    output_dropped: requireSafeUint(raw.output_dropped, "terminal output_dropped"),
  };
}

function parseLoop(value: unknown): RustAgentLoopSnapshot {
  const raw = requireRecord(value, "AgentLoop snapshot");
  if (raw.contract_version !== AGENT_LOOP_CONTRACT_VERSION) {
    throw new ExecutionCheckpointError(`unsupported AgentLoop contract version: ${String(raw.contract_version)}`);
  }
  const spec = requireRecord(raw.spec, "AgentLoop spec");
  const state = raw.state;
  if (typeof state !== "string" || !(LOOP_STATES as readonly string[]).includes(state)) {
    throw new ExecutionCheckpointError(`unknown AgentLoop state: ${String(state)}`);
  }
  const snapshot: RustAgentLoopSnapshot = {
    contract_version: AGENT_LOOP_CONTRACT_VERSION,
    spec: {
      loop_id: requireIdentity(spec.loop_id, "loop_id", AGENT_LOOP_MAX_ID_BYTES),
      agent_id: requireIdentity(spec.agent_id, "loop agent_id", AGENT_LOOP_MAX_ID_BYTES),
      cell_id: requireIdentity(spec.cell_id, "loop cell_id", AGENT_LOOP_MAX_ID_BYTES),
      session_id: requireIdentity(spec.session_id, "loop session_id", AGENT_LOOP_MAX_ID_BYTES),
      terminal_id: requireIdentity(spec.terminal_id, "loop terminal_id", AGENT_LOOP_MAX_ID_BYTES),
    },
    state: state as RustAgentLoopState,
    next_command_seq: requireSafeUint(raw.next_command_seq, "next_command_seq", 1),
    accepted_commands: requireSafeUint(raw.accepted_commands, "accepted_commands"),
    failed_commands: requireSafeUint(raw.failed_commands, "failed_commands"),
    lock_wait_ns: requireSafeUint(raw.lock_wait_ns, "lock_wait_ns"),
  };
  if (snapshot.accepted_commands >= snapshot.next_command_seq) {
    throw new ExecutionCheckpointError("accepted_commands exceeds AgentLoop sequence cursor");
  }
  return snapshot;
}

/** Validate a Rust execution checkpoint without opening a live runtime. */
export function validateExecutionStoreDocument(value: unknown): RustExecutionStoreDocument {
  const raw = requireRecord(value, "execution store document");
  if (raw.store_version !== EXECUTION_STORE_VERSION) {
    throw new ExecutionCheckpointError(`unsupported execution store version: ${String(raw.store_version)}`);
  }
  const cleanShutdown = requireBoolean(raw.clean_shutdown, "execution clean_shutdown");
  const generation = requireSafeUint(raw.generation, "execution generation");
  if (!Array.isArray(raw.sessions) || !Array.isArray(raw.terminals) || !Array.isArray(raw.loops)) {
    throw new ExecutionCheckpointError("sessions, terminals, and loops must be arrays");
  }
  const sessionDocument = validateSessionStoreDocument({
    store_version: SESSION_STORE_VERSION,
    generation: 0,
    clean_shutdown: cleanShutdown,
    sessions: raw.sessions,
  });
  const sessions = sessionDocument.sessions;
  const terminals = raw.terminals.map(parseTerminal);
  const loops = raw.loops.map(parseLoop);
  sortedUnique(sessions.map((checkpoint) => checkpoint.snapshot.spec.session_id), "sessions");
  sortedUnique(terminals.map((snapshot) => snapshot.terminal_id), "terminals");
  sortedUnique(loops.map((snapshot) => snapshot.spec.loop_id), "loops");

  const sessionIds = new Set(sessions.map((checkpoint) => checkpoint.snapshot.spec.session_id));
  const terminalIds = new Set(terminals.map((snapshot) => snapshot.terminal_id));
  for (const terminal of terminals) {
    if (terminal.session_id !== null && !sessionIds.has(terminal.session_id)) {
      throw new ExecutionCheckpointError(`terminal ${terminal.terminal_id} references missing session ${terminal.session_id}`);
    }
    if (cleanShutdown) {
      if (terminal.process_id !== null) throw new ExecutionCheckpointError("clean document contains a live process binding");
      if (["ready", "running"].includes(terminal.state)) {
        throw new ExecutionCheckpointError(`clean document contains active terminal ${terminal.terminal_id}`);
      }
      if (terminal.input_depth !== 0 || terminal.output_depth !== 0) {
        throw new ExecutionCheckpointError(`clean document contains queued terminal frames for ${terminal.terminal_id}`);
      }
    }
  }
  for (const loop of loops) {
    if (!sessionIds.has(loop.spec.session_id)) {
      throw new ExecutionCheckpointError(`AgentLoop ${loop.spec.loop_id} references missing session ${loop.spec.session_id}`);
    }
    if (!terminalIds.has(loop.spec.terminal_id)) {
      throw new ExecutionCheckpointError(`AgentLoop ${loop.spec.loop_id} references missing terminal ${loop.spec.terminal_id}`);
    }
    if (cleanShutdown && ["ready", "running", "paused", "closing"].includes(loop.state)) {
      throw new ExecutionCheckpointError(`clean document contains active AgentLoop ${loop.spec.loop_id}`);
    }
  }
  return {
    store_version: EXECUTION_STORE_VERSION,
    generation,
    clean_shutdown: cleanShutdown,
    sessions,
    terminals,
    loops,
  };
}

/** Return a fresh empty execution document. */
export function emptyExecutionStoreDocument(): RustExecutionStoreDocument {
  return {
    store_version: EXECUTION_STORE_VERSION,
    generation: 0,
    clean_shutdown: true,
    sessions: [],
    terminals: [],
    loops: [],
  };
}

/** Decode and validate a JSON execution checkpoint. */
export function decodeExecutionStoreDocument(text: string): RustExecutionStoreDocument {
  if (typeof text !== "string" || text.trim().length === 0) {
    throw new ExecutionCheckpointError("execution store document must be non-empty text");
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw new ExecutionCheckpointError(`invalid execution store json: ${String(error)}`);
  }
  return validateExecutionStoreDocument(value);
}

/** Encode a validated document deterministically without writing to disk. */
export function encodeExecutionStoreDocument(document: RustExecutionStoreDocument): string {
  return canonicalJson(validateExecutionStoreDocument(document));
}

/** Read-only file adapter for the Rust-owned execution checkpoint. */
export class RustExecutionStoreReader {
  private constructor(
    private readonly checkpointPath: string,
    private current: RustExecutionStoreDocument,
  ) {}

  /** Open a state root, treating an absent or empty checkpoint as fresh. */
  static async open(root: string): Promise<RustExecutionStoreReader> {
    const rootStat = await stat(root).catch((error: unknown) => {
      if (isNotFound(error)) return undefined;
      throw error;
    });
    if (rootStat && !rootStat.isDirectory()) {
      throw new ExecutionCheckpointError(`state root is not a directory: ${root}`);
    }
    const checkpointPath = path.join(root, EXECUTION_STORE_RELATIVE_PATH);
    const contents = await readFile(checkpointPath, "utf8").catch((error: unknown) => {
      if (isNotFound(error)) return "";
      throw error;
    });
    const current = contents.trim().length === 0 ? emptyExecutionStoreDocument() : decodeExecutionStoreDocument(contents);
    return new RustExecutionStoreReader(checkpointPath, current);
  }

  /** Return the absolute checkpoint path used by this reader. */
  checkpointFile(): string {
    return this.checkpointPath;
  }

  /** Return a defensive copy of the last validated document. */
  document(): RustExecutionStoreDocument {
    return structuredClone(this.current);
  }

  /** Re-read the checkpoint for a fresh read-only projection. */
  async refresh(): Promise<RustExecutionStoreDocument> {
    const contents = await readFile(this.checkpointPath, "utf8").catch((error: unknown) => {
      if (isNotFound(error)) return "";
      throw error;
    });
    this.current = contents.trim().length === 0 ? emptyExecutionStoreDocument() : decodeExecutionStoreDocument(contents);
    return this.document();
  }
}

function isNotFound(error: unknown): boolean {
  return isRecord(error) && error.code === "ENOENT";
}
