/**
 * Real end-to-end: TS bridge over the stdio transport against the actual
 * Python ProtocolHost (python -m l2.protocol), proving the protocol v1
 * contract round-trips across languages.
 *
 * Python path is overridable via PRAXIS_PYTHON; the host runs from the
 * repo src/ directory so `l2` and `l3` packages resolve on sys.path.
 */

import { spawn } from "node:child_process";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ProtocolBridge } from "../src/engine/bridge.ts";
import { createStdioTransport } from "../src/engine/transports/stdio.ts";

const PYTHON = process.env.PRAXIS_PYTHON ?? "/home/guiling/dev/praxis/.venv/bin/python";
const SRC_DIR = path.resolve(process.cwd(), "../..", "src");

describe("e2e stdio host", () => {
  let proc: ReturnType<typeof spawn>;
  let bridge: ProtocolBridge;
  let stderrLog = "";

  beforeAll(() => {
    proc = spawn(PYTHON, ["-m", "l2.protocol"], { cwd: SRC_DIR, stdio: ["pipe", "pipe", "pipe"] });
    proc.stderr.on("data", (chunk) => {
      stderrLog += String(chunk);
    });
    const transport = createStdioTransport({ input: proc.stdout, output: proc.stdin, timeoutMs: 30000 });
    bridge = new ProtocolBridge({ sessionId: "s-e2e", transport });
  }, 30000);

  afterAll(() => {
    proc.kill();
  });

  it("round-trips a command through the real Python ProtocolHost", async () => {
    const responses = await bridge.command("lang");
    const result = responses.find((message) => message.kind === "result");
    expect(result).toBeDefined();
    expect(result?.payload.success).toBe(true);
  }, 30000);

  it("attaches a view and replays the session window", async () => {
    const attached = await bridge.attach("s-e2e", "view-e2e");
    expect(attached.some((message) => message.kind === "event" && message.payload.name === "session.attached")).toBe(true);

    const replay = await bridge.replay("s-e2e", "view-e2e");
    expect(replay.some((message) => message.kind === "event")).toBe(true);
  }, 30000);
});
