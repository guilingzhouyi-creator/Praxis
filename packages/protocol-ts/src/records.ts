/** Versioned TypeScript mirror of the Python3 TS-neutral protocol records. */

export const RECORD_SCHEMA_VERSION = 1 as const;
export const RECORD_TYPES = [
  "decision_summary",
  "event_envelope",
  "evidence_ref",
  "session_identity",
  "session_message",
  "tool_failure",
] as const;

export type RecordType = (typeof RECORD_TYPES)[number];
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface SessionIdentity {
  session_id: string;
  terminal_id: string;
  process_id: string;
  user_id: string;
  role: string;
  cell_id: string;
  memory_scope: string;
}

export interface EventEnvelope {
  event_id: string;
  session_id: string;
  seq: number;
  event_type: string;
  payload: JsonObject;
  input_seq: number | null;
  trace_id: string;
  ts: number;
}

export interface SessionMessage {
  message_id: string;
  session_id: string;
  input_seq: number;
  role: string;
  content: string;
  trace_id: string;
  ts: number;
}

export interface ToolFailure {
  failure_id: string;
  session_id: string;
  input_seq: number;
  tool_name: string;
  error_kind: string;
  message: string;
  retryable: boolean;
  trace_id: string;
  ts: number;
}

export interface DecisionSummary {
  decision_id: string;
  session_id: string;
  input_seq: number;
  summary: string;
  outcome: string;
  evidence_refs: string[];
  trace_id: string;
  ts: number;
}

export interface EvidenceRef {
  evidence_id: string;
  session_id: string;
  input_seq: number;
  kind: string;
  locator: string;
  digest: string;
  trace_id: string;
  metadata: JsonObject;
}

export interface ProtocolRecord<Data = JsonObject> {
  record_type: RecordType;
  schema_version: typeof RECORD_SCHEMA_VERSION;
  data: Data;
}

export type SessionIdentityRecord = ProtocolRecord<SessionIdentity> & { record_type: "session_identity" };
export type EventEnvelopeRecord = ProtocolRecord<EventEnvelope> & { record_type: "event_envelope" };
export type SessionMessageRecord = ProtocolRecord<SessionMessage> & { record_type: "session_message" };
export type ToolFailureRecord = ProtocolRecord<ToolFailure> & { record_type: "tool_failure" };
export type DecisionSummaryRecord = ProtocolRecord<DecisionSummary> & { record_type: "decision_summary" };
export type EvidenceRefRecord = ProtocolRecord<EvidenceRef> & { record_type: "evidence_ref" };
export type AnyRecord =
  | SessionIdentityRecord
  | EventEnvelopeRecord
  | SessionMessageRecord
  | ToolFailureRecord
  | DecisionSummaryRecord
  | EvidenceRefRecord;

export class RecordValidationError extends Error {
  /** Report an invalid or unsupported protocol record. */
  constructor(message: string) {
    super(message);
    this.name = "RecordValidationError";
  }
}

const KNOWN_FIELDS: { [K in RecordType]: readonly string[] } = {
  session_identity: ["session_id", "terminal_id", "process_id", "user_id", "role", "cell_id", "memory_scope"],
  event_envelope: ["event_id", "session_id", "seq", "event_type", "payload", "input_seq", "trace_id", "ts"],
  session_message: ["message_id", "session_id", "input_seq", "role", "content", "trace_id", "ts"],
  tool_failure: [
    "failure_id",
    "session_id",
    "input_seq",
    "tool_name",
    "error_kind",
    "message",
    "retryable",
    "trace_id",
    "ts",
  ],
  decision_summary: ["decision_id", "session_id", "input_seq", "summary", "outcome", "evidence_refs", "trace_id", "ts"],
  evidence_ref: ["evidence_id", "session_id", "input_seq", "kind", "locator", "digest", "trace_id", "metadata"],
};

const REQUIRED_FIELDS: { [K in RecordType]: readonly string[] } = {
  session_identity: ["session_id", "terminal_id", "process_id"],
  event_envelope: ["event_id", "session_id", "seq", "event_type", "payload"],
  session_message: ["message_id", "session_id", "input_seq", "role", "content"],
  tool_failure: ["failure_id", "session_id", "input_seq", "tool_name", "error_kind", "message", "retryable"],
  decision_summary: ["decision_id", "session_id", "input_seq", "summary", "outcome"],
  evidence_ref: ["evidence_id", "session_id", "input_seq", "kind", "locator"],
};

const DEFAULT_FIELDS: { [K in RecordType]: JsonObject } = {
  session_identity: { user_id: "", role: "", cell_id: "", memory_scope: "" },
  event_envelope: { input_seq: null, trace_id: "" },
  session_message: { trace_id: "" },
  tool_failure: { trace_id: "" },
  decision_summary: { evidence_refs: [], trace_id: "" },
  evidence_ref: { digest: "", trace_id: "", metadata: {} },
};

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasField(object: JsonObject, field: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, field);
}

function requireText(value: unknown, name: string, allowEmpty = false): void {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    throw new RecordValidationError(`${name} must be a ${allowEmpty ? "string" : "non-empty string"}`);
  }
}

function requireInteger(value: unknown, name: string, minimum = 0): void {
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) {
    throw new RecordValidationError(`${name} must be an integer >= ${minimum}`);
  }
}

function requireTimestamp(value: unknown): void {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new RecordValidationError("ts must be a number");
  }
}

function requireObject(value: unknown, name: string): asserts value is JsonObject {
  if (!isObject(value)) {
    throw new RecordValidationError(`${name} must be an object`);
  }
}

function requireStringArray(value: unknown, name: string): void {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new RecordValidationError(`${name} must be a string array`);
  }
}

function validateData(recordType: RecordType, data: JsonObject): void {
  for (const field of REQUIRED_FIELDS[recordType]) {
    if (!hasField(data, field)) {
      throw new RecordValidationError(`missing record fields: ${field}`);
    }
  }
  switch (recordType) {
    case "session_identity":
      requireText(data.session_id, "session_id");
      requireText(data.terminal_id, "terminal_id");
      requireText(data.process_id, "process_id");
      for (const field of ["user_id", "role", "cell_id", "memory_scope"]) requireText(data[field], field, true);
      return;
    case "event_envelope":
      requireText(data.event_id, "event_id");
      requireText(data.session_id, "session_id");
      requireInteger(data.seq, "seq");
      requireText(data.event_type, "event_type");
      requireObject(data.payload, "payload");
      if (data.input_seq !== null) requireInteger(data.input_seq, "input_seq", 1);
      requireText(data.trace_id, "trace_id", true);
      requireTimestamp(data.ts);
      return;
    case "session_message":
      requireText(data.message_id, "message_id");
      requireText(data.session_id, "session_id");
      requireInteger(data.input_seq, "input_seq", 1);
      requireText(data.role, "role");
      requireText(data.content, "content", true);
      requireText(data.trace_id, "trace_id", true);
      requireTimestamp(data.ts);
      return;
    case "tool_failure":
      requireText(data.failure_id, "failure_id");
      requireText(data.session_id, "session_id");
      requireInteger(data.input_seq, "input_seq", 1);
      requireText(data.tool_name, "tool_name");
      requireText(data.error_kind, "error_kind");
      requireText(data.message, "message", true);
      if (typeof data.retryable !== "boolean") throw new RecordValidationError("retryable must be a boolean");
      requireText(data.trace_id, "trace_id", true);
      requireTimestamp(data.ts);
      return;
    case "decision_summary":
      requireText(data.decision_id, "decision_id");
      requireText(data.session_id, "session_id");
      requireInteger(data.input_seq, "input_seq", 1);
      requireText(data.summary, "summary", true);
      requireText(data.outcome, "outcome");
      requireStringArray(data.evidence_refs, "evidence_refs");
      requireText(data.trace_id, "trace_id", true);
      requireTimestamp(data.ts);
      return;
    case "evidence_ref":
      requireText(data.evidence_id, "evidence_id");
      requireText(data.session_id, "session_id");
      requireInteger(data.input_seq, "input_seq", 1);
      requireText(data.kind, "kind");
      requireText(data.locator, "locator");
      requireText(data.digest, "digest", true);
      requireText(data.trace_id, "trace_id", true);
      requireObject(data.metadata, "metadata");
      return;
  }
}

function nowSeconds(): number {
  return Date.now() / 1000;
}

function normalizeRecord(raw: unknown): AnyRecord {
  requireObject(raw, "record");
  const recordType = raw.record_type;
  if (typeof recordType !== "string" || !(RECORD_TYPES as readonly string[]).includes(recordType)) {
    throw new RecordValidationError(`unknown record_type: ${String(recordType)}`);
  }
  if (raw.schema_version !== RECORD_SCHEMA_VERSION) {
    throw new RecordValidationError(`unsupported record schema version: ${String(raw.schema_version)}`);
  }
  requireObject(raw.data, "record data");
  const data: JsonObject = { ...DEFAULT_FIELDS[recordType as RecordType] };
  if (recordType !== "session_identity" && !hasField(raw.data, "ts")) data.ts = nowSeconds();
  for (const field of KNOWN_FIELDS[recordType as RecordType]) {
    if (hasField(raw.data, field)) data[field] = raw.data[field];
  }
  validateData(recordType as RecordType, data);
  return { record_type: recordType as RecordType, schema_version: RECORD_SCHEMA_VERSION, data } as unknown as AnyRecord;
}

function sortJson(value: unknown): JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new RecordValidationError("non-finite number cannot be encoded as JSON");
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => sortJson(item));
  if (isObject(value)) {
    const result: JsonObject = {};
    for (const key of Object.keys(value).sort()) {
      const item = value[key];
      if (item === undefined) throw new RecordValidationError(`undefined value at ${key}`);
      result[key] = sortJson(item);
    }
    return result;
  }
  throw new RecordValidationError(`unsupported JSON value: ${typeof value}`);
}

export function canonicalJson(value: unknown): string {
  /** Serialize JSON values with recursively sorted keys for Python3 parity. */
  const encoded = JSON.stringify(sortJson(value));
  if (encoded === undefined) throw new RecordValidationError("value cannot be encoded as JSON");
  return encoded;
}

export function toRecordEnvelope(record: AnyRecord): AnyRecord {
  /** Normalize a record and discard forward-compatible unknown fields. */
  return normalizeRecord(record);
}

export function encodeRecord(record: AnyRecord): string {
  /** Serialize a record using the Python3 reference's canonical JSON rules. */
  return canonicalJson(toRecordEnvelope(record));
}

export function decodeRecord(line: string): AnyRecord {
  /** Decode one record and fail closed on malformed JSON or schema versions. */
  if (typeof line !== "string" || line.trim().length === 0) {
    throw new RecordValidationError("record line must be non-empty text");
  }
  let raw: unknown;
  try {
    raw = JSON.parse(line);
  } catch (error) {
    throw new RecordValidationError(`invalid record json: ${String(error)}`);
  }
  return normalizeRecord(raw);
}
