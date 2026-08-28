/** Parity tests for the TypeScript protocol mirror. */

import { describe, expect, it } from "vitest";
import fixtures from "../../../tests/fixtures/protocol_v1_records.json";
import {
  RECORD_SCHEMA_VERSION,
  RecordValidationError,
  canonicalJson,
  decodeRecord,
  encodeRecord,
  type AnyRecord,
} from "../src/wire-records.ts";
import {
  KINDS,
  Outbox,
  SessionCursor,
  decodeMessage,
  encodeMessage,
  makeMessage,
  validateMessage,
} from "../src/wire-envelope.ts";

describe("TS-neutral records", () => {
  it("decodes every shared Python3 fixture and emits canonical JSON", () => {
    for (const fixture of fixtures) {
      const decoded = decodeRecord(JSON.stringify(fixture)) as AnyRecord;
      expect(JSON.parse(encodeRecord(decoded))).toEqual(fixture);
      expect(encodeRecord(decoded)).toBe(encodeRecord(decoded));
    }
  });

  it("ignores unknown fields but rejects unsupported versions", () => {
    const fixture = fixtures[0] as Record<string, unknown>;
    const withUnknown = {
      ...fixture,
      future_field: true,
      data: { ...(fixture.data as Record<string, unknown>), future_context: "ignored" },
    };
    expect(decodeRecord(JSON.stringify(withUnknown))).toEqual(decodeRecord(JSON.stringify(fixture)));

    const future = { ...fixture, schema_version: RECORD_SCHEMA_VERSION + 1 };
    expect(() => decodeRecord(JSON.stringify(future))).toThrow(RecordValidationError);
  });

  it("rejects records missing required fields", () => {
    const fixture = fixtures[0] as Record<string, unknown>;
    const missing = { ...fixture, data: { ...(fixture.data as Record<string, unknown>) } };
    delete (missing.data as Record<string, unknown>).session_id;
    expect(() => decodeRecord(JSON.stringify(missing))).toThrow(/missing record fields: session_id/);
  });

  it("rejects unknown record types and non-object record data", () => {
    const fixture = fixtures[0] as Record<string, unknown>;
    expect(() => decodeRecord(JSON.stringify({ ...fixture, record_type: "no_such_type" }))).toThrow(/unknown record_type/);
    expect(() => decodeRecord(JSON.stringify({ ...fixture, data: "not-an-object" }))).toThrow(/must be an object/);
    expect(() => decodeRecord(JSON.stringify({ ...fixture, data: null }))).toThrow(/must be an object/);
    expect(() => decodeRecord("{\"record_type\":\"session_identity\"}")).toThrow(RecordValidationError);
  });

  it("rejects unparsable lines and non-finite payload values", () => {
    expect(() => decodeRecord("{not json")).toThrow(RecordValidationError);
    expect(() => canonicalJson(Number.NaN)).toThrow(/non-finite number/);
    expect(() => canonicalJson({ a: undefined })).toThrow(/undefined value at a/);
  });

  it("rejects payloads that are not objects and string arrays with empty items", () => {
    const event = fixtures.find((f) => (f as { record_type: string }).record_type === "event_envelope") as Record<string, unknown>;
    expect(() => decodeRecord(JSON.stringify({ ...event, data: { ...(event.data as Record<string, unknown>), payload: "x" } }))).toThrow(/payload must be an object/);

    const summary = fixtures.find((f) => (f as { record_type: string }).record_type === "decision_summary") as Record<string, unknown>;
    expect(() => decodeRecord(JSON.stringify({ ...summary, data: { ...(summary.data as Record<string, unknown>), evidence_refs: ["ok", ""] } }))).toThrow(/must be a string array/);
    expect(() => decodeRecord(JSON.stringify({ ...summary, data: { ...(summary.data as Record<string, unknown>), evidence_refs: [42] } }))).toThrow(/must be a string array/);
  });
});

describe("protocol v1 envelope", () => {
  it("matches Python3 message construction and round-trip", () => {
    const message = makeMessage("s-1", 7, "command", { name: "status" }, "trace-1", 100.0);
    expect(validateMessage(message)).toEqual([]);
    const decoded = decodeMessage(encodeMessage(message));
    expect(decoded.error).toBeNull();
    expect(decoded.message).toEqual(message);
    expect(KINDS).toEqual(["ack", "command", "control", "event", "intent", "result", "stream_chunk"]);
  });

  it("accepts envelopes that omit the optional trace id", () => {
    const message = { ...makeMessage("s-1", 1, "event", {}, "", 0), trace_id: undefined };
    delete message.trace_id;
    expect(validateMessage(message)).toEqual([]);
    expect(decodeMessage(JSON.stringify(message)).error).toBeNull();
  });

  it("keeps the bounded replay window and cursor semantics", () => {
    const outbox = new Outbox(2);
    for (const seq of [1, 2, 3]) outbox.append(makeMessage("s-1", seq, "result", { success: true }, "", 0));
    expect(outbox.unacked().map((message) => message.seq)).toEqual([2, 3]);
    outbox.ack(2);
    expect(outbox.unacked().map((message) => message.seq)).toEqual([3]);
    expect(outbox.lastAcked).toBe(2);

    const cursor = new SessionCursor("web-1");
    cursor.attach("s-1");
    expect(cursor.attached).toBe(true);
    cursor.detach();
    expect(cursor.attached).toBe(false);
  });

  it("mirrors the Python3 non-destructive ack across views", () => {
    const outbox = new Outbox();
    for (const seq of [1, 2]) outbox.append(makeMessage("s-1", seq, "result", { success: true }, "", 0));
    outbox.ack(1);
    // The advancing view sees only its future; a lagging view replays all.
    expect(outbox.unacked().map((message) => message.seq)).toEqual([2]);
    expect(outbox.unacked(0).map((message) => message.seq)).toEqual([1, 2]);

    const cursor = new SessionCursor("view-a");
    cursor.ack(5);
    expect(cursor.lastAcked).toBe(5);
    cursor.ack(3);
    expect(cursor.lastAcked).toBe(5);
  });
});
