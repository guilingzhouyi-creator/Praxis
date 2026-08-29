/** Cross-language canonical envelope check: TS, Python reference, and Rust gate. */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { encodeMessage, makeMessage, type Message, type MessageKind } from "../src/protocol/wire-envelope.ts";

const PACKAGE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(PACKAGE_DIR, "../..");
const FIXTURE_PATH = path.join(REPO_ROOT, "tests/fixtures/protocol_v1_conformance.json");
const RUST_GATE = path.join(REPO_ROOT, "systems/rust-kernel-engine/target/debug/rust-protocol-gate");
const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as {
  canonical_envelopes: Array<{ fields: { session_id: string; seq: number; ts: number; trace_id: string; kind: string; payload: Record<string, never> }; expected_line: string }>;
};

function build(fields: (typeof fixture.canonical_envelopes)[number]["fields"]): Message {
  return makeMessage(
    fields.session_id,
    fields.seq,
    fields.kind as MessageKind,
    fields.payload as Message["payload"],
    fields.trace_id,
    fields.ts,
  );
}

describe("protocol v1 three-way canonical vectors", () => {
  it("matches the Python reference and Rust gate byte-for-byte", () => {
    if (!existsSync(RUST_GATE)) return;
    const expected = fixture.canonical_envelopes.map((item) => item.expected_line);
    const tsLines = fixture.canonical_envelopes.map((item) => encodeMessage(build(item.fields)));
    expect(tsLines).toEqual(expected);

    const input = `${expected.join("\n")}\n`;
    const rustLines = execFileSync(RUST_GATE, [], { cwd: REPO_ROOT, input, encoding: "utf8" })
      .trim()
      .split("\n");
    expect(rustLines).toEqual(expected);

    const python = process.env.PRAXIS_PYTHON ?? "python";
    const pythonCode = [
      "import sys",
      "from l2.protocol.envelope import decode_message, encode_message",
      "for line in sys.stdin:",
      "    msg, err = decode_message(line)",
      "    if err: raise SystemExit(err)",
      "    print(encode_message(msg))",
    ].join("\n");
    const pythonLines = execFileSync(python, ["-c", pythonCode], {
      cwd: path.join(REPO_ROOT, "systems/python-reference-runtime"),
      input,
      encoding: "utf8",
    }).trim().split("\n");
    expect(pythonLines).toEqual(expected);
  });
});
