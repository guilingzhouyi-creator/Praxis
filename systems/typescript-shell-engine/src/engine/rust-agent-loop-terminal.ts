/**
 * Read-only TypeScript projection of the Rust terminal-backed AgentLoop seam.
 *
 * Rust owns the live terminal, session, AgentLoop, and execution state. This
 * module validates the versioned correlation/frame values received by a
 * transport and provides defensive byte copies for rendering or forwarding.
 * It never dequeues mailboxes, admits session messages, executes actions, or
 * chooses a shell, encoding, PTY, or provider.
 */

import type {
  RustAgentLoopSpec,
  RustTerminalState,
} from "./execution-checkpoint.ts";

/** Rust terminal-to-AgentLoop composition contract version. */
export const AGENT_LOOP_TERMINAL_CONTRACT_VERSION = 1 as const;
/** Maximum number of frames accepted by one grouped bridge call. */
export const AGENT_LOOP_TERMINAL_MAX_BATCH = 256 as const;
/** Maximum opaque bytes accepted in one terminal frame. */
export const TERMINAL_MAX_FRAME_BYTES = 1_048_576 as const;
/** Maximum UTF-8 bytes retained for one logical identity. */
export const AGENT_LOOP_TERMINAL_MAX_ID_BYTES = 128 as const;

/** Direction carried by one Rust terminal mailbox frame. */
export type RustTerminalStream = "input" | "output" | "error";

/** Defensive local representation of one opaque Rust terminal frame. */
export interface RustTerminalFrame {
  sequence: number;
  stream: RustTerminalStream;
  data: Uint8Array;
}

/** Versioned loop/session/terminal correlation emitted by Rust preflight. */
export interface RustAgentLoopTerminalBinding {
  contract_version: typeof AGENT_LOOP_TERMINAL_CONTRACT_VERSION;
  spec: RustAgentLoopSpec;
  session_id: string;
  terminal_state: RustTerminalState;
}

const TERMINAL_STREAMS: readonly RustTerminalStream[] = ["input", "output", "error"];
const TERMINAL_STATES: readonly RustTerminalState[] = ["created", "ready", "running", "stopped", "closed"];
const UTF8_ENCODER = new TextEncoder();

/** Parse and validate one Rust loop/terminal binding. */
export function parseRustAgentLoopTerminalBinding(
  input: unknown,
): RustAgentLoopTerminalBinding | null {
  if (!isRecord(input) || input.contract_version !== AGENT_LOOP_TERMINAL_CONTRACT_VERSION) return null;
  const spec = parseSpec(input.spec);
  const sessionId = parseIdentity(input.session_id);
  const state = input.terminal_state;
  if (!spec || !sessionId || typeof state !== "string" || !TERMINAL_STATES.includes(state as RustTerminalState)) {
    return null;
  }
  if (spec.session_id !== sessionId) return null;
  if (spec.terminal_id.length === 0) return null;
  return {
    contract_version: AGENT_LOOP_TERMINAL_CONTRACT_VERSION,
    spec,
    session_id: sessionId,
    terminal_state: state as RustTerminalState,
  };
}

/**
 * Parse one Rust JSON frame. JSON transports carry `Vec<u8>` as a bounded
 * array of byte integers; local callers may pass a `Uint8Array` directly.
 */
export function parseRustTerminalFrame(input: unknown): RustTerminalFrame | null {
  if (!isRecord(input)) return null;
  const sequence = input.sequence;
  const stream = input.stream;
  if (
    typeof sequence !== "number"
    || !Number.isSafeInteger(sequence)
    || sequence < 1
    || typeof stream !== "string"
    || !TERMINAL_STREAMS.includes(stream as RustTerminalStream)
  ) {
    return null;
  }
  const data = parseBytes(input.data);
  if (!data) return null;
  return {
    sequence,
    stream: stream as RustTerminalStream,
    data,
  };
}

/** Parse a bounded frame batch, optionally requiring one stream direction. */
export function parseRustTerminalFrameBatch(
  input: unknown,
  expectedStream?: RustTerminalStream,
  maxBatch = AGENT_LOOP_TERMINAL_MAX_BATCH,
): RustTerminalFrame[] | null {
  if (
    !Array.isArray(input)
    || !Number.isSafeInteger(maxBatch)
    || maxBatch < 1
    || maxBatch > AGENT_LOOP_TERMINAL_MAX_BATCH
    || input.length > maxBatch
  ) {
    return null;
  }
  const parsed: RustTerminalFrame[] = [];
  for (let index = 0; index < input.length; index += 1) {
    if (!Object.prototype.hasOwnProperty.call(input, index)) return null;
    const frame = parseRustTerminalFrame(input[index]);
    if (!frame) return null;
    parsed.push(frame);
  }
  if (expectedStream && parsed.some((frame) => frame.stream !== expectedStream)) return null;
  return parsed;
}

/** Encode a validated local frame into the JSON shape emitted by Rust serde. */
export function encodeRustTerminalFrame(frame: RustTerminalFrame): {
  sequence: number;
  stream: RustTerminalStream;
  data: number[];
} | null {
  const parsed = parseRustTerminalFrame({
    sequence: frame.sequence,
    stream: frame.stream,
    data: frame.data,
  });
  if (!parsed) return null;
  return {
    sequence: parsed.sequence,
    stream: parsed.stream,
    data: [...parsed.data],
  };
}

/**
 * Bounded read model that prevents a frontend from mixing terminal frames
 * across different Rust loop/session/terminal identities.
 */
export class RustAgentLoopTerminalProjection {
  private current: RustAgentLoopTerminalBinding | null = null;

  /** Accept the first binding or an equivalent subsequent snapshot. */
  updateBinding(input: unknown): boolean {
    const next = parseRustAgentLoopTerminalBinding(input);
    if (!next) return false;
    if (
      this.current
      && (
        this.current.spec.loop_id !== next.spec.loop_id
        || this.current.spec.agent_id !== next.spec.agent_id
        || this.current.spec.cell_id !== next.spec.cell_id
        || this.current.spec.session_id !== next.spec.session_id
        || this.current.spec.terminal_id !== next.spec.terminal_id
      )
    ) {
      return false;
    }
    this.current = next;
    return true;
  }

  /** Return a defensive copy of the current binding, if one is accepted. */
  binding(): RustAgentLoopTerminalBinding | null {
    if (!this.current) return null;
    return {
      ...this.current,
      spec: { ...this.current.spec },
    };
  }

  /** Parse an input-only frame for the currently projected terminal. */
  inputFrame(input: unknown): RustTerminalFrame | null {
    if (!this.current) return null;
    const frame = parseRustTerminalFrame(input);
    return frame?.stream === "input" ? cloneFrame(frame) : null;
  }

  /** Parse an output/error frame for the currently projected terminal. */
  outputFrame(input: unknown): RustTerminalFrame | null {
    if (!this.current) return null;
    const frame = parseRustTerminalFrame(input);
    return frame && frame.stream !== "input" ? cloneFrame(frame) : null;
  }

  /** Clear the local projection without changing Rust-owned state. */
  clear(): void {
    this.current = null;
  }
}

function parseSpec(input: unknown): RustAgentLoopSpec | null {
  if (!isRecord(input)) return null;
  const loopId = parseIdentity(input.loop_id);
  const agentId = parseIdentity(input.agent_id);
  const cellId = parseIdentity(input.cell_id);
  const sessionId = parseIdentity(input.session_id);
  const terminalId = parseIdentity(input.terminal_id);
  if (!loopId || !agentId || !cellId || !sessionId || !terminalId) return null;
  return {
    loop_id: loopId,
    agent_id: agentId,
    cell_id: cellId,
    session_id: sessionId,
    terminal_id: terminalId,
  };
}

function parseIdentity(input: unknown): string | null {
  if (typeof input !== "string" || input.trim().length === 0 || input.includes("\0")) return null;
  if (UTF8_ENCODER.encode(input).byteLength > AGENT_LOOP_TERMINAL_MAX_ID_BYTES) return null;
  return input;
}

function parseBytes(input: unknown): Uint8Array | null {
  if (input instanceof Uint8Array) {
    if (input.byteLength > TERMINAL_MAX_FRAME_BYTES) return null;
    return new Uint8Array(input);
  }
  if (!Array.isArray(input) || input.length > TERMINAL_MAX_FRAME_BYTES) {
    return null;
  }
  const bytes: number[] = [];
  for (let index = 0; index < input.length; index += 1) {
    if (!Object.prototype.hasOwnProperty.call(input, index)) return null;
    const value = input[index];
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 255) return null;
    bytes.push(value);
  }
  return Uint8Array.from(bytes);
}

function cloneFrame(frame: RustTerminalFrame): RustTerminalFrame {
  return {
    sequence: frame.sequence,
    stream: frame.stream,
    data: new Uint8Array(frame.data),
  };
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null && !Array.isArray(input);
}
