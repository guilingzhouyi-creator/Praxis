/**
 * Rust-host end-to-end slice. The test is skipped when the candidate binary
 * has not been built; CI can enable it after `cargo build --bin
 * rust-protocol-host` without changing the TS test command.
 */

import { existsSync } from "node:fs";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ProtocolBridge } from "../src/engine/bridge.ts";
import {
  createRustHostTransport,
  defaultRustHostBinary,
  type ManagedHostTransport,
} from "../src/engine/transports/rust-host.ts";

const rustHostSuite = existsSync(defaultRustHostBinary()) ? describe : describe.skip;

rustHostSuite("e2e Rust protocol host", () => {
  let managed: ManagedHostTransport;
  let bridge: ProtocolBridge;

  beforeAll(() => {
    managed = createRustHostTransport({ timeoutMs: 30_000 });
    bridge = new ProtocolBridge({ sessionId: "s-rust-e2e", transport: managed });
  }, 30_000);

  afterAll(() => managed.close());

  it("returns a result and trailing ack for an L1 command", async () => {
    const responses = await bridge.command("status");
    expect(responses.some((message) => message.kind === "result")).toBe(true);
    expect(responses.some((message) => message.kind === "ack")).toBe(true);
  }, 30_000);

  it("preserves attach/recovery session boundaries", async () => {
    const attached = await bridge.attach("s-rust-e2e", "view-rust");
    expect(attached.some((message) => message.kind === "ack")).toBe(true);
    expect(attached.some((message) => message.kind === "event" && message.payload.name === "session.attached")).toBe(true);
    const replay = await bridge.replay("s-rust-e2e", "view-rust", -1);
    expect(replay.some((message) => message.kind === "ack")).toBe(true);
    expect(replay.some((message) => message.kind === "event" && message.payload.name === "session.recovered")).toBe(true);
  }, 30_000);
});
