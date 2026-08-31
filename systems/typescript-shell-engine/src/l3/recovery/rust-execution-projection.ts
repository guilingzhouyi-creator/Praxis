/**
 * Validated projection of the Rust-owned execution checkpoint.
 *
 * Rust owns the durable `ExecutionStoreDocument`. This module accepts only
 * detached JSON-shaped data, validates the lower-layer correlation vectors,
 * and exposes metadata-only projections to L3. Session message bodies and
 * process handles never become TypeScript state.
 */

import type { AgentIdentity, AgentRuntimeError } from "../contracts/agent-contracts.ts";
import { AgentRuntimeError as RuntimeError } from "../contracts/agent-contracts.ts";
import type { JsonObject } from "../../protocol/wire-records.ts";
import { L3_MAX_RUST_PROJECTION_ENTITIES } from "../runtime/limits.ts";

/** Rust execution-store document schema accepted by this adapter. */
export const RUST_EXECUTION_STORE_VERSION = 1 as const;
/** Rust session checkpoint schema accepted by this adapter. */
export const RUST_SESSION_CHECKPOINT_VERSION = 1 as const;
/** Rust session snapshot schema accepted by this adapter. */
export const RUST_SESSION_CONTRACT_VERSION = 1 as const;
/** Rust AgentLoop snapshot schema accepted by this adapter. */
export const RUST_AGENT_LOOP_CONTRACT_VERSION = 1 as const;

/** Rust session lifecycle values projected into the TS recovery boundary. */
export type RustSessionState = "created" | "active" | "closing" | "closed" | "crashed";
/** Rust AgentLoop lifecycle values projected into the TS recovery boundary. */
export type RustAgentLoopState =
  | "created"
  | "ready"
  | "running"
  | "paused"
  | "closing"
  | "stopped"
  | "failed";
/** Rust terminal lifecycle values projected into the TS recovery boundary. */
export type RustTerminalState = "created" | "ready" | "running" | "stopped" | "closed";

/** Metadata-only session snapshot; message bodies are intentionally omitted. */
export interface RustSessionProjection {
  readonly sessionId: string;
  readonly agentId: string;
  readonly cellId: string;
  readonly role: string;
  readonly maxMessages: number;
  readonly state: RustSessionState;
  readonly nextInputSeq: number;
  readonly nextMessageSeq: number;
  readonly cleanShutdown: boolean;
  readonly retainedMessages: number;
}

/** Metadata-only terminal snapshot; the process handle is reduced to a flag. */
export interface RustTerminalProjection {
  readonly terminalId: string;
  readonly state: RustTerminalState;
  readonly sessionId: string | null;
  readonly processBound: boolean;
  readonly inputCapacity: number;
  readonly outputCapacity: number;
  readonly inputDepth: number;
  readonly outputDepth: number;
  readonly inputDropped: number;
  readonly outputDropped: number;
}

/** Metadata-only AgentLoop snapshot carrying the Rust command cursor. */
export interface RustAgentLoopProjection {
  readonly loopId: string;
  readonly agentId: string;
  readonly cellId: string;
  readonly sessionId: string;
  readonly terminalId: string;
  readonly state: RustAgentLoopState;
  readonly nextCommandSeq: number;
  readonly acceptedCommands: number;
  readonly failedCommands: number;
  readonly lockWaitNs: number;
}

/** Fully validated, detached Rust execution-store projection. */
export interface RustExecutionProjection {
  readonly storeVersion: typeof RUST_EXECUTION_STORE_VERSION;
  readonly generation: number;
  readonly cleanShutdown: boolean;
  readonly sessions: readonly RustSessionProjection[];
  readonly terminals: readonly RustTerminalProjection[];
  readonly loops: readonly RustAgentLoopProjection[];
}

/** One identity-correlated view of the Rust execution projection. */
export interface RustIdentityProjection {
  readonly storeVersion: typeof RUST_EXECUTION_STORE_VERSION;
  readonly generation: number;
  readonly cleanShutdown: boolean;
  readonly session: RustSessionProjection;
  readonly terminal: RustTerminalProjection;
  readonly loop: RustAgentLoopProjection;
}

type PlainRecord = Record<string, unknown>;

function invalid(message: string, details?: JsonObject): AgentRuntimeError {
  return new RuntimeError("recovery_invalid", message, details);
}

function isPlainRecord(value: unknown): value is PlainRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function object(value: unknown, name: string): PlainRecord {
  if (!isPlainRecord(value)) throw invalid(`${name} must be a plain object`);
  return value;
}

function text(value: unknown, name: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0) || value.includes("\0")) {
    throw invalid(`${name} must be a ${allowEmpty ? "string" : "non-empty string"} without NUL`);
  }
  return value;
}

function safeInteger(value: unknown, name: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    throw invalid(`${name} must be a safe integer >= ${minimum}`);
  }
  return value;
}

function boolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") throw invalid(`${name} must be a boolean`);
  return value;
}

function nullableText(value: unknown, name: string): string | null {
  if (value === null || value === undefined) return null;
  return text(value, name);
}

function array(value: unknown, name: string): readonly unknown[] {
  if (!Array.isArray(value)) throw invalid(`${name} must be an array`);
  if (value.length > L3_MAX_RUST_PROJECTION_ENTITIES) {
      throw invalid(`${name} exceeds the projection entity bound`, {
      name,
      count: value.length,
      limit: L3_MAX_RUST_PROJECTION_ENTITIES,
    });
  }
  return value;
}

function enumeration<T extends string>(
  value: unknown,
  name: string,
  values: readonly T[],
): T {
  if (typeof value !== "string" || !values.includes(value as T)) {
    throw invalid(`${name} is not a supported lifecycle value`);
  }
  return value as T;
}

function unique(values: readonly string[], name: string): void {
  const seen = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) throw invalid(`${name} contains a duplicate identity: ${value}`);
    seen.add(value);
  }
}

function parseSessionCheckpoint(value: unknown): RustSessionProjection {
  const checkpoint = object(value, "session checkpoint");
  if (safeInteger(checkpoint.checkpoint_version, "session checkpoint_version") !== RUST_SESSION_CHECKPOINT_VERSION) {
    throw invalid("unsupported Rust session checkpoint version");
  }
  const snapshot = object(checkpoint.snapshot, "session snapshot");
  if (safeInteger(snapshot.contract_version, "session contract_version") !== RUST_SESSION_CONTRACT_VERSION) {
    throw invalid("unsupported Rust session contract version");
  }
  const spec = object(snapshot.spec, "session spec");
  const sessionId = text(spec.session_id, "session spec.session_id");
  const agentId = text(spec.agent_id, "session spec.agent_id");
  const cellId = text(spec.cell_id, "session spec.cell_id");
  const role = text(spec.role, "session spec.role", true);
  const maxMessages = safeInteger(spec.max_messages, "session spec.max_messages", 1);
  const messages = array(snapshot.messages, "session messages");
  if (messages.length > maxMessages) {
    throw invalid("session retained messages exceed max_messages");
  }
  for (const [index, messageValue] of messages.entries()) {
    const message = object(messageValue, `session message ${index}`);
    safeInteger(message.sequence, `session message ${index}.sequence`, 1);
    safeInteger(message.input_seq, `session message ${index}.input_seq`, 1);
    text(message.message_id, `session message ${index}.message_id`);
    text(message.role, `session message ${index}.role`);
    text(message.content, `session message ${index}.content`, true);
    safeInteger(message.created_at_ns, `session message ${index}.created_at_ns`);
  }
  return {
    sessionId,
    agentId,
    cellId,
    role,
    maxMessages,
    state: enumeration(snapshot.state, "session state", ["created", "active", "closing", "closed", "crashed"]),
    nextInputSeq: safeInteger(snapshot.next_input_seq, "session next_input_seq", 1),
    nextMessageSeq: safeInteger(snapshot.next_message_seq, "session next_message_seq", 1),
    cleanShutdown: boolean(snapshot.clean_shutdown, "session clean_shutdown"),
    retainedMessages: messages.length,
  };
}

function parseTerminal(value: unknown, index: number): RustTerminalProjection {
  const terminal = object(value, `terminal ${index}`);
  const terminalId = text(terminal.terminal_id, `terminal ${index}.terminal_id`);
  const processId = terminal.process_id;
  if (processId !== null && processId !== undefined) safeInteger(processId, `terminal ${index}.process_id`, 1);
  return {
    terminalId,
    state: enumeration(terminal.state, `terminal ${index}.state`, ["created", "ready", "running", "stopped", "closed"]),
    sessionId: nullableText(terminal.session_id, `terminal ${index}.session_id`),
    processBound: processId !== null && processId !== undefined,
    inputCapacity: safeInteger(terminal.input_capacity, `terminal ${index}.input_capacity`, 1),
    outputCapacity: safeInteger(terminal.output_capacity, `terminal ${index}.output_capacity`, 1),
    inputDepth: safeInteger(terminal.input_depth, `terminal ${index}.input_depth`),
    outputDepth: safeInteger(terminal.output_depth, `terminal ${index}.output_depth`),
    inputDropped: safeInteger(terminal.input_dropped, `terminal ${index}.input_dropped`),
    outputDropped: safeInteger(terminal.output_dropped, `terminal ${index}.output_dropped`),
  };
}

function parseLoop(value: unknown, index: number): RustAgentLoopProjection {
  const loop = object(value, `AgentLoop ${index}`);
  if (safeInteger(loop.contract_version, `AgentLoop ${index}.contract_version`) !== RUST_AGENT_LOOP_CONTRACT_VERSION) {
    throw invalid("unsupported Rust AgentLoop contract version");
  }
  const spec = object(loop.spec, `AgentLoop ${index}.spec`);
  return {
    loopId: text(spec.loop_id, `AgentLoop ${index}.spec.loop_id`),
    agentId: text(spec.agent_id, `AgentLoop ${index}.spec.agent_id`),
    cellId: text(spec.cell_id, `AgentLoop ${index}.spec.cell_id`),
    sessionId: text(spec.session_id, `AgentLoop ${index}.spec.session_id`),
    terminalId: text(spec.terminal_id, `AgentLoop ${index}.spec.terminal_id`),
    state: enumeration(loop.state, `AgentLoop ${index}.state`, [
      "created",
      "ready",
      "running",
      "paused",
      "closing",
      "stopped",
      "failed",
    ]),
    nextCommandSeq: safeInteger(loop.next_command_seq, `AgentLoop ${index}.next_command_seq`, 1),
    acceptedCommands: safeInteger(loop.accepted_commands, `AgentLoop ${index}.accepted_commands`),
    failedCommands: safeInteger(loop.failed_commands, `AgentLoop ${index}.failed_commands`),
    lockWaitNs: safeInteger(loop.lock_wait_ns, `AgentLoop ${index}.lock_wait_ns`),
  };
}

/**
 * Parse and validate one detached Rust execution-store JSON document.
 *
 * A JSON string is accepted for transport adapters that have not decoded the
 * host response yet. No filesystem or Rust object is accessed here.
 */
export function parseRustExecutionProjection(value: unknown): RustExecutionProjection {
  let decoded = value;
  if (typeof value === "string") {
    try {
      decoded = JSON.parse(value) as unknown;
    } catch {
      throw invalid("Rust execution projection is not valid JSON");
    }
  }
  const document = object(decoded, "Rust execution projection");
  if (safeInteger(document.store_version, "store_version") !== RUST_EXECUTION_STORE_VERSION) {
    throw invalid("unsupported Rust execution-store version");
  }
  const sessions = array(document.sessions, "sessions").map(parseSessionCheckpoint);
  const terminals = array(document.terminals, "terminals").map(parseTerminal);
  const loops = array(document.loops, "loops").map(parseLoop);
  unique(sessions.map((session) => session.sessionId), "sessions");
  unique(terminals.map((terminal) => terminal.terminalId), "terminals");
  unique(loops.map((loop) => loop.loopId), "AgentLoops");
  return {
    storeVersion: RUST_EXECUTION_STORE_VERSION,
    generation: safeInteger(document.generation, "generation"),
    cleanShutdown: boolean(document.clean_shutdown, "clean_shutdown"),
    sessions,
    terminals,
    loops,
  };
}

/**
 * Correlate one complete L3 identity with its Rust session, terminal, and
 * logical AgentLoop snapshots.
 */
export function projectRustIdentity(
  projection: RustExecutionProjection,
  identity: AgentIdentity,
): RustIdentityProjection {
  const session = projection.sessions.find((candidate) => candidate.sessionId === identity.sessionId);
  if (!session) {
    throw new RuntimeError("recovery_missing", `Rust session is missing: ${identity.sessionId}`);
  }
  if (session.agentId !== identity.agentId || session.cellId !== identity.cellId) {
    throw new RuntimeError("recovery_invalid", "Rust session identity does not match the L3 identity");
  }
  const terminal = projection.terminals.find((candidate) => candidate.terminalId === identity.terminalId);
  if (!terminal) {
    throw new RuntimeError("recovery_missing", `Rust terminal is missing: ${identity.terminalId}`);
  }
  if (terminal.sessionId !== identity.sessionId) {
    throw new RuntimeError("recovery_invalid", "Rust terminal/session correlation does not match the L3 identity");
  }
  const matches = projection.loops.filter((candidate) =>
    candidate.agentId === identity.agentId
    && candidate.cellId === identity.cellId
    && candidate.sessionId === identity.sessionId
    && candidate.terminalId === identity.terminalId
  );
  if (matches.length === 0) {
    throw new RuntimeError("recovery_missing", "Rust AgentLoop is missing for the L3 identity");
  }
  if (matches.length > 1) {
    throw new RuntimeError("recovery_invalid", "Rust projection contains multiple AgentLoops for one L3 identity");
  }
  return {
    storeVersion: projection.storeVersion,
    generation: projection.generation,
    cleanShutdown: projection.cleanShutdown,
    session,
    terminal,
    loop: matches[0]!,
  };
}

/** Return a detached identity copy for projection adapters. */
export function copyRustIdentityProjection(projection: RustIdentityProjection): RustIdentityProjection {
  return {
    ...projection,
    session: { ...projection.session },
    terminal: { ...projection.terminal },
    loop: { ...projection.loop },
  };
}
