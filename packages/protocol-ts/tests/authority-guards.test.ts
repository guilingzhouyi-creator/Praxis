import { describe, it, expect } from "vitest";
import {
  makeMessage, validateMessage, encodeMessage, decodeMessage,
  Outbox, SessionCursor,
} from "../src/envelope.ts";
import { RecordValidationError, canonicalJson, decodeRecord, encodeRecord } from "../src/records.ts";

const VALID = () => makeMessage("sess", 1, "event", { ok: true });

describe("validateMessage fail-closed branches", () => {
  it("rejects non-object envelopes", () => {
    expect(validateMessage("string")).toEqual(["envelope must be an object"]);
    expect(validateMessage(42)).toEqual(["envelope must be an object"]);
    expect(validateMessage(null)).toEqual(["envelope must be an object"]);
  });

  it("reports every missing required field", () => {
    const errors = validateMessage({});
    for (const field of ["v", "session_id", "seq", "ts", "kind", "payload"]) {
      expect(errors).toContain(`missing field: ${field}`);
    }
  });

  it("rejects unsupported protocol version and bad seq/ts/kind", () => {
    const m = VALID() as unknown as Record<string, unknown>;
    m.v = 999;
    expect(validateMessage(m)).toContain("unsupported version: 999");
    const m2 = { ...VALID(), seq: -1 } as unknown as Record<string, unknown>;
    expect(validateMessage(m2)).toContain("seq must be a non-negative integer");
    const m3 = { ...VALID(), ts: "not-a-number" } as unknown as Record<string, unknown>;
    expect(validateMessage(m3)).toContain("ts must be a number");
    const m4 = { ...VALID(), kind: "bogus" } as unknown as Record<string, unknown>;
    expect(validateMessage(m4)).toContain("unknown kind: bogus");
    const m5 = { ...VALID(), session_id: "" } as unknown as Record<string, unknown>;
    expect(validateMessage(m5)).toContain("session_id must be a non-empty string");
    const unsafe = { ...VALID(), seq: Number.MAX_SAFE_INTEGER + 1 } as unknown as Record<string, unknown>;
    expect(validateMessage(unsafe)).toContain("seq must be a non-negative integer");
  });

  it("rejects non-string trace_id", () => {
    const m = { ...VALID(), trace_id: 123 } as unknown as Record<string, unknown>;
    expect(validateMessage(m)).toContain("trace_id must be a string");
  });

  it("accepts valid string trace_id", () => {
    const m = { ...VALID(), trace_id: "abc" };
    expect(validateMessage(m)).toEqual([]);
  });

  it("rejects non-object payload before kind checks", () => {
    const m = { ...VALID(), payload: "nope" };
    expect(validateMessage(m)).toContain("payload must be an object");
  });

  it("validates per-kind payload contracts", () => {
    const bad = (kind: string, payload: object) =>
      validateMessage({ ...VALID(), kind, payload });
    expect(bad("command", {})).toContain("command payload requires a non-empty name");
    expect(bad("command", { name: "x", args: [1] })).toContain("command payload args must be a string array");
    expect(bad("intent", { text: "" })).toContain("intent payload requires non-empty text");
    expect(bad("result", { success: "yes" })).toContain("result payload requires boolean success");
    expect(bad("stream_chunk", { data: 9 })).toContain("stream_chunk payload requires string data");
    expect(bad("control", { op: "explode" })).toContain("control payload has unknown op: explode");
    expect(bad("control", { op: "attach", session_id: "" })).toContain(
      "control payload session_id must be a non-empty string",
    );
    expect(bad("ack", { ack_seq: -2 })).toContain("ack payload requires a non-negative integer ack_seq");
    expect(bad("ack", { ack_seq: Number.MAX_SAFE_INTEGER + 1 })).toContain(
      "ack payload requires a non-negative integer ack_seq",
    );
  });

  it("encodeMessage throws on invalid envelope; decodeMessage reports without throwing", () => {
    expect(() => encodeMessage({ ...VALID(), seq: -1 })).toThrow(/seq/);
    expect(decodeMessage("").error).toBe("empty line");
    expect(decodeMessage("   ").error).toBe("empty line");
    expect(decodeMessage("{broken").error).toMatch(/^invalid json/);
    const badEnvelope = JSON.stringify({ ...VALID(), kind: "bogus" });
    expect(decodeMessage(badEnvelope).error).toContain("unknown kind: bogus");
    const ok = decodeMessage(JSON.stringify(VALID()));
    expect(ok.error).toBeNull();
    expect(ok.message).toBeTruthy();
  });
});

describe("Outbox authority semantics", () => {
  it("non-destructive ack preserves replay window", () => {
    const box = new Outbox(8);
    box.append(makeMessage("sess", 1, "event", { ok: true }));
    box.append(makeMessage("sess", 2, "event", { ok: true }));
    expect(box.size).toBe(2);
    box.ack(1);
    expect(box.lastAcked).toBe(1);
    // Acked messages remain buffered for other views' replay.
    expect(box.unacked(-1)).toHaveLength(2);
    expect(box.unacked(1)).toHaveLength(1);
  });

  it("evicts oldest beyond maxlen while keeping ack cursor monotonic", () => {
    const box = new Outbox(2);
    box.ack(5);
    box.append(makeMessage("s", 6, "event", {}));
    box.append(makeMessage("s", 7, "event", {}));
    box.append(makeMessage("s", 8, "event", {}));
    expect(box.size).toBeLessThanOrEqual(2);
    expect(box.lastAcked).toBe(5);
  });

  it("ignores regressive acks", () => {
    const box = new Outbox(4);
    box.ack(10);
    box.ack(3);
    expect(box.lastAcked).toBe(10);
  });
});

describe("SessionCursor per-view semantics", () => {
  it("attach/detach toggles replay eligibility", () => {
    const cur = new SessionCursor("view-web");
    expect(cur.attached).toBe(false);
    cur.attach("sess-1");
    expect(cur.attached).toBe(true);
    expect(cur.sessionId).toBe("sess-1");
    cur.detach();
    expect(cur.attached).toBe(false);
  });

  it("ack is monotonic across out-of-order deliveries", () => {
    const cur = new SessionCursor("v");
    cur.ack(7);
    cur.ack(2);
    cur.ack(12);
    expect(cur.lastAcked).toBe(12);
  });
});

describe("records fail-closed paths", () => {
  const baseRecord = {
    record_type: "session_identity",
    schema_version: 1,
    data: { session_id: "s-1", terminal_id: "t-1", process_id: "p-1", role: "worker" },
  };

  it("canonicalJson sorts keys recursively for python parity", () => {
    expect(canonicalJson({ b: 1, a: { d: 2, c: [3, { z: 1, y: 2 }] } }))
      .toBe('{"a":{"c":[3,{"y":2,"z":1}],"d":2},"b":1}');
  });

  it("throws on non-finite numbers and undefined values", () => {
    expect(() => canonicalJson({ x: Number.NaN })).toThrow(RecordValidationError);
    expect(() => canonicalJson({ x: undefined })).toThrow(/undefined value at x/);
  });

  it("throws on unsupported JSON value types", () => {
    expect(() => canonicalJson({ f: () => 1 })).toThrow(/unsupported JSON value/);
  });

  it("decodeRecord rejects empty lines and malformed json", () => {
    expect(() => decodeRecord("")).toThrow(/non-empty/);
    expect(() => decodeRecord("   ")).toThrow(/non-empty/);
    expect(() => decodeRecord("{oops")).toThrow(/invalid record json/);
  });

  it("round-trips a record through encode/decode preserving fields", () => {
    const encoded = encodeRecord(baseRecord);
    const decoded = decodeRecord(encoded);
    expect(decoded.record_type).toBe("session_identity");
  });
});
