import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { Outbox, decodeMessage, encodeMessage, makeMessage, validateMessage } from "../src/protocol/wire-envelope.ts";
import { parseRoute } from "../src/engine/route.ts";
import type { Message, MessageKind } from "../src/protocol/wire-types.ts";

const fixturePath = fileURLToPath(
  new URL("../../../tests/fixtures/protocol_v1_conformance.json", import.meta.url),
);
const fixture = JSON.parse(readFileSync(fixturePath, "utf-8"));

function buildMessage(fields: {
  session_id: string;
  seq: number;
  ts: number;
  trace_id: string;
  kind: string;
  payload: Record<string, unknown>;
}): Message {
  return makeMessage(
    fields.session_id,
    fields.seq,
    fields.kind as MessageKind,
    fields.payload as Message["payload"],
    fields.trace_id,
    fields.ts,
  );
}

describe("canonical encoding matches frozen bytes (TS normative source)", () => {
  it.each(fixture.canonical_envelopes.map((c: { name: string }) => c))(
    "$name",
    (caseItem: {
      fields: Parameters<typeof buildMessage>[0];
      expected_line: string;
    }) => {
      const message = buildMessage(caseItem.fields);
      expect(validateMessage(message)).toHaveLength(0);
      expect(encodeMessage(message)).toBe(caseItem.expected_line);
      const decoded = decodeMessage(caseItem.expected_line);
      expect(decoded.error).toBeNull();
      expect(decoded.message).toEqual(JSON.parse(caseItem.expected_line));
    },
  );
});

describe("invalid frames fail closed on every implementation", () => {
  it.each(fixture.invalid_frames.map((c: { name: string }) => c))(
    "$name",
    (caseItem: { line: string; error_contains_any: string[] }) => {
      const decoded = decodeMessage(caseItem.line);
      expect(decoded.error).not.toBeNull();
      const hit = caseItem.error_contains_any.some((fragment) =>
        (decoded.error as string).includes(fragment),
      );
      expect(hit).toBe(true);
    },
  );
});

describe("R1 outbox recovery semantics", () => {
  it.each(fixture.outbox_recovery.map((c: { name: string }) => c))(
    "$name",
    (caseItem: {
      maxlen: number;
      append_seqs: number[];
      ack: number | null;
      expect_default_unacked: number[];
      expect_recovery_from_minus_one: number[];
    }) => {
      const box = new Outbox(caseItem.maxlen);
      for (const seq of caseItem.append_seqs) {
        box.append(makeMessage("s", seq, "intent", { text: "x" }));
      }
      if (caseItem.ack !== null) box.ack(caseItem.ack);
      expect(box.unacked().map((m) => m.seq)).toEqual(caseItem.expect_default_unacked);
      expect(box.unacked(-1).map((m) => m.seq)).toEqual(caseItem.expect_recovery_from_minus_one);
    },
  );
});

describe("R6 dialect routing order", () => {
  it.each(fixture.route_classification_r6.map((c: { line: string }) => c))(
    "$line",
    (caseItem: { line: string; kind: string; [key: string]: unknown }) => {
      const route = parseRoute(caseItem.line) as Record<string, unknown>;
      expect(route.kind).toBe(caseItem.kind);
      for (const key of ["command", "name", "args"]) {
        if (key in caseItem) expect(route[key]).toEqual(caseItem[key]);
      }
    },
  );
});
