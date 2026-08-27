/**
 * Rust session-store codec for the clean-break L1/L2 boundary.
 *
 * The shape mirrors `systems/rust-kernel-engine/l1-kernel-rs/src/session_store.rs` exactly. This
 * module is deliberately separate from the legacy Python-facing
 * `ISessionPersistence` contract: TS can inspect and stage Rust checkpoints,
 * while Rust remains the authority for live session state and recovery.
 */

import { mkdir, open, readFile, rename, rm, stat } from "node:fs/promises";
import path from "node:path";

import { canonicalJson } from "../wire-records.ts";

/** Rust session-store document schema version. */
export const SESSION_STORE_VERSION = 1 as const;
/** Rust session checkpoint envelope version. */
export const SESSION_CHECKPOINT_VERSION = 1 as const;
/** Rust session mechanism contract version. */
export const SESSION_CONTRACT_VERSION = 1 as const;
/** Rust-owned relative checkpoint path below a state root. */
export const SESSION_STORE_RELATIVE_PATH = "snapshots/sessions/checkpoint.json" as const;
/** Maximum identity-field length accepted by the Rust session contract. */
export const SESSION_MAX_ID_BYTES = 128 as const;
/** Maximum role length accepted by the Rust session contract. */
export const SESSION_MAX_ROLE_BYTES = 32 as const;
/** Maximum message body length accepted by the Rust session contract. */
export const SESSION_MAX_CONTENT_BYTES = 1 << 20;
/** Maximum retained messages accepted by the Rust session contract. */
export const SESSION_MAX_MESSAGES = 16_384 as const;

export type RustSessionState = "created" | "active" | "closing" | "closed" | "crashed";
export type RustMessageRole = "system" | "user" | "assistant" | "tool";

/** Declarative identity and retention policy owned by the Rust session book. */
export interface RustSessionSpec {
  session_id: string;
  agent_id: string;
  cell_id: string;
  role: string;
  max_messages: number;
}

/** One retained Rust session history entry. */
export interface RustSessionMessage {
  sequence: number;
  input_seq: number;
  message_id: string;
  role: RustMessageRole;
  content: string;
  created_at_ns: number;
}

/** Serializable Rust session state. */
export interface RustSessionSnapshot {
  contract_version: typeof SESSION_CONTRACT_VERSION;
  spec: RustSessionSpec;
  state: RustSessionState;
  next_input_seq: number;
  next_message_seq: number;
  clean_shutdown: boolean;
  messages: RustSessionMessage[];
}

/** Versioned Rust checkpoint envelope. */
export interface RustSessionCheckpoint {
  checkpoint_version: typeof SESSION_CHECKPOINT_VERSION;
  snapshot: RustSessionSnapshot;
}

/** Versioned collection written by Rust `SessionStore`. */
export interface RustSessionStoreDocument {
  store_version: typeof SESSION_STORE_VERSION;
  generation: number;
  clean_shutdown: boolean;
  sessions: RustSessionCheckpoint[];
}

/** Fail-closed error raised for malformed or unsafe checkpoint data. */
export class SessionCheckpointError extends Error {
  /** Describe one rejected checkpoint boundary. */
  constructor(message: string) {
    super(message);
    this.name = "SessionCheckpointError";
  }
}

const SESSION_STATES: readonly RustSessionState[] = ["created", "active", "closing", "closed", "crashed"];
const MESSAGE_ROLES: readonly RustMessageRole[] = ["system", "user", "assistant", "tool"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function textBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function requireRecord(value: unknown, name: string): Record<string, unknown> {
  if (!isRecord(value)) throw new SessionCheckpointError(`${name} must be an object`);
  return value;
}

function requireText(value: unknown, name: string, maxBytes: number): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new SessionCheckpointError(`${name} must be a non-empty string`);
  }
  if (textBytes(value) > maxBytes) throw new SessionCheckpointError(`${name} exceeds ${maxBytes} bytes`);
  return value;
}

function requireSafeUint(value: unknown, name: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    throw new SessionCheckpointError(`${name} must be a safe integer >= ${minimum}`);
  }
  return value;
}

function requireBoolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") throw new SessionCheckpointError(`${name} must be a boolean`);
  return value;
}

function parseSpec(value: unknown): RustSessionSpec {
  const raw = requireRecord(value, "session spec");
  const maxMessages = requireSafeUint(raw.max_messages, "max_messages", 1);
  if (maxMessages > SESSION_MAX_MESSAGES) {
    throw new SessionCheckpointError(`max_messages exceeds ${SESSION_MAX_MESSAGES}`);
  }
  return {
    session_id: requireText(raw.session_id, "session_id", SESSION_MAX_ID_BYTES),
    agent_id: requireText(raw.agent_id, "agent_id", SESSION_MAX_ID_BYTES),
    cell_id: requireText(raw.cell_id, "cell_id", SESSION_MAX_ID_BYTES),
    role: requireText(raw.role, "role", SESSION_MAX_ID_BYTES),
    max_messages: maxMessages,
  };
}

function parseMessage(value: unknown, maxMessages: number): RustSessionMessage {
  const raw = requireRecord(value, "session message");
  const role = raw.role;
  if (typeof role !== "string" || !(MESSAGE_ROLES as readonly string[]).includes(role)) {
    throw new SessionCheckpointError(`unknown message role: ${String(role)}`);
  }
  if (textBytes(role) > SESSION_MAX_ROLE_BYTES) {
    throw new SessionCheckpointError(`message role exceeds ${SESSION_MAX_ROLE_BYTES} bytes`);
  }
  const content = raw.content;
  if (typeof content !== "string") throw new SessionCheckpointError("message content must be a string");
  if (textBytes(content) > SESSION_MAX_CONTENT_BYTES) {
    throw new SessionCheckpointError(`message content exceeds ${SESSION_MAX_CONTENT_BYTES} bytes`);
  }
  const messageId = requireText(raw.message_id, "message_id", SESSION_MAX_ID_BYTES);
  if (maxMessages < 1) throw new SessionCheckpointError("max_messages must be positive");
  return {
    sequence: requireSafeUint(raw.sequence, "message sequence", 1),
    input_seq: requireSafeUint(raw.input_seq, "message input_seq", 1),
    message_id: messageId,
    role: role as RustMessageRole,
    content,
    created_at_ns: requireSafeUint(raw.created_at_ns, "created_at_ns"),
  };
}

function parseSnapshot(value: unknown): RustSessionSnapshot {
  const raw = requireRecord(value, "session snapshot");
  if (raw.contract_version !== SESSION_CONTRACT_VERSION) {
    throw new SessionCheckpointError(`unsupported session contract version: ${String(raw.contract_version)}`);
  }
  const spec = parseSpec(raw.spec);
  const state = raw.state;
  if (typeof state !== "string" || !(SESSION_STATES as readonly string[]).includes(state)) {
    throw new SessionCheckpointError(`unknown session state: ${String(state)}`);
  }
  const cleanShutdown = requireBoolean(raw.clean_shutdown, "snapshot clean_shutdown");
  if (state === "crashed" && cleanShutdown) {
    throw new SessionCheckpointError("crashed session cannot claim clean shutdown");
  }
  const nextInputSeq = requireSafeUint(raw.next_input_seq, "next_input_seq", 1);
  const nextMessageSeq = requireSafeUint(raw.next_message_seq, "next_message_seq", 1);
  if (!Array.isArray(raw.messages)) throw new SessionCheckpointError("messages must be an array");
  if (raw.messages.length > spec.max_messages || raw.messages.length > SESSION_MAX_MESSAGES) {
    throw new SessionCheckpointError("message history exceeds retention capacity");
  }
  const messages = raw.messages.map((message) => parseMessage(message, spec.max_messages));
  const ids = new Set<string>();
  let previousSequence = 0;
  let highestInput = 0;
  for (const message of messages) {
    if (message.sequence <= previousSequence) throw new SessionCheckpointError("message sequences must increase");
    if (ids.has(message.message_id)) throw new SessionCheckpointError(`duplicate message_id: ${message.message_id}`);
    if (message.input_seq >= nextInputSeq) {
      throw new SessionCheckpointError("message input_seq is outside the authoritative range");
    }
    ids.add(message.message_id);
    previousSequence = message.sequence;
    if (message.role === "user") highestInput = Math.max(highestInput, message.input_seq);
  }
  if (nextMessageSeq <= previousSequence || nextInputSeq <= highestInput) {
    throw new SessionCheckpointError("next sequence counters do not follow retained history");
  }
  return {
    contract_version: SESSION_CONTRACT_VERSION,
    spec,
    state: state as RustSessionState,
    next_input_seq: nextInputSeq,
    next_message_seq: nextMessageSeq,
    clean_shutdown: cleanShutdown,
    messages,
  };
}

function parseCheckpoint(value: unknown): RustSessionCheckpoint {
  const raw = requireRecord(value, "session checkpoint");
  if (raw.checkpoint_version !== SESSION_CHECKPOINT_VERSION) {
    throw new SessionCheckpointError(`unsupported checkpoint version: ${String(raw.checkpoint_version)}`);
  }
  return { checkpoint_version: SESSION_CHECKPOINT_VERSION, snapshot: parseSnapshot(raw.snapshot) };
}

/** Validate and normalize one Rust session-store document. */
export function validateSessionStoreDocument(value: unknown): RustSessionStoreDocument {
  const raw = requireRecord(value, "session store document");
  if (raw.store_version !== SESSION_STORE_VERSION) {
    throw new SessionCheckpointError(`unsupported store version: ${String(raw.store_version)}`);
  }
  const cleanShutdown = requireBoolean(raw.clean_shutdown, "store clean_shutdown");
  if (!Array.isArray(raw.sessions)) throw new SessionCheckpointError("sessions must be an array");
  const sessions = raw.sessions.map(parseCheckpoint);
  let previousId: string | undefined;
  for (const checkpoint of sessions) {
    const sessionId = checkpoint.snapshot.spec.session_id;
    if (previousId !== undefined && previousId >= sessionId) {
      throw new SessionCheckpointError("sessions must be sorted and unique by session_id");
    }
    if (
      cleanShutdown
      && ["active", "closing", "crashed"].includes(checkpoint.snapshot.state)
    ) {
      throw new SessionCheckpointError("clean document contains a non-terminal session");
    }
    previousId = sessionId;
  }
  return {
    store_version: SESSION_STORE_VERSION,
    generation: requireSafeUint(raw.generation, "generation"),
    clean_shutdown: cleanShutdown,
    sessions,
  };
}

/** Return an empty document with the same defaults as Rust `SessionStore`. */
export function emptySessionStoreDocument(): RustSessionStoreDocument {
  return { store_version: SESSION_STORE_VERSION, generation: 0, clean_shutdown: true, sessions: [] };
}

/** Decode and validate a JSON document from the Rust-owned checkpoint file. */
export function decodeSessionStoreDocument(text: string): RustSessionStoreDocument {
  if (typeof text !== "string" || text.trim().length === 0) {
    throw new SessionCheckpointError("session store document must be non-empty text");
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw new SessionCheckpointError(`invalid session store json: ${String(error)}`);
  }
  return validateSessionStoreDocument(value);
}

/** Encode a validated document using deterministic recursively sorted JSON. */
export function encodeSessionStoreDocument(document: RustSessionStoreDocument): string {
  return canonicalJson(validateSessionStoreDocument(document));
}

/** File adapter for the Rust-owned checkpoint path; never mutates live Rust state. */
export class RustSessionStore {
  private writeTail: Promise<void> = Promise.resolve();

  private constructor(
    private readonly checkpointPath: string,
    private current: RustSessionStoreDocument,
  ) {}

  /** Open a Rust state root, treating an absent or empty checkpoint as fresh. */
  static async open(root: string): Promise<RustSessionStore> {
    const rootStat = await stat(root).catch((error: unknown) => {
      if (isNotFound(error)) return undefined;
      throw error;
    });
    if (rootStat && !rootStat.isDirectory()) throw new SessionCheckpointError(`state root is not a directory: ${root}`);
    const checkpointPath = path.join(root, SESSION_STORE_RELATIVE_PATH);
    const contents = await readFile(checkpointPath, "utf8").catch((error: unknown) => {
      if (isNotFound(error)) return "";
      throw error;
    });
    const current = contents.trim().length === 0 ? emptySessionStoreDocument() : decodeSessionStoreDocument(contents);
    return new RustSessionStore(checkpointPath, current);
  }

  /** Return the absolute checkpoint path used by this adapter. */
  checkpointFile(): string {
    return this.checkpointPath;
  }

  /** Return a defensive copy of the latest validated document. */
  document(): RustSessionStoreDocument {
    return structuredClone(this.current);
  }

  /** Persist the next monotonically generated document with an atomic replace. */
  async save(document: RustSessionStoreDocument): Promise<void> {
    const write = this.writeTail.then(() => this.saveUnlocked(document));
    this.writeTail = write.catch(() => undefined);
    return write;
  }

  private async saveUnlocked(document: RustSessionStoreDocument): Promise<void> {
    const normalized = validateSessionStoreDocument(document);
    if (normalized.generation !== this.current.generation + 1) {
      throw new SessionCheckpointError(
        `generation must advance by one (expected ${this.current.generation + 1}, got ${normalized.generation})`,
      );
    }
    const parent = path.dirname(this.checkpointPath);
    await mkdir(parent, { recursive: true });
    const temporary = `${this.checkpointPath}.tmp-${process.pid}-${Date.now()}`;
    let committed = false;
    try {
      const handle = await open(temporary, "wx");
      try {
        await handle.writeFile(`${encodeSessionStoreDocument(normalized)}\n`, "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      await rename(temporary, this.checkpointPath);
      committed = true;
      this.current = normalized;
    } finally {
      if (!committed) await rm(temporary, { force: true }).catch(() => undefined);
    }
  }
}

function isNotFound(error: unknown): boolean {
  return isRecord(error) && error.code === "ENOENT";
}
