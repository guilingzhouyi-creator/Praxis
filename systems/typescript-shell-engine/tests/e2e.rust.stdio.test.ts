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

const rustHostCommand = process.env.PRAXIS_RUST_HOST_BIN?.trim() || defaultRustHostBinary();
const rustHostAvailable =
  Boolean(process.env.PRAXIS_RUST_HOST_BIN?.trim()) &&
  (rustHostCommand.includes("/") || rustHostCommand.includes("\\")) &&
  existsSync(rustHostCommand);
const rustHostSuite = rustHostAvailable ? describe : describe.skip;

rustHostSuite("e2e Rust protocol host", () => {
  let managed: ManagedHostTransport;
  let bridge: ProtocolBridge;

  beforeAll(() => {
    managed = createRustHostTransport({ command: rustHostCommand, timeoutMs: 30_000 });
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

  it("denies unregistered commands fail-closed with a trailing ack", async () => {
    const responses = await bridge.command("no-such-command-xyz");
    expect(
      responses.some(
        (message) =>
          message.kind === "result" && message.payload.success === false && String(message.payload.error).includes("unregistered command"),
      ),
    ).toBe(true);
    expect(responses.some((message) => message.kind === "ack")).toBe(true);
  }, 30_000);

  it("keeps one view's replay window intact after another view acks", async () => {
    await bridge.attach("s-multi", "view-a");
    await bridge.attach("s-multi", "view-b");
    const ackResponses = await bridge.ack(100, "view-a", "s-multi");
    expect(ackResponses.some((message) => message.kind === "ack")).toBe(true);
    // Non-destructive R1: view-a acking must not erase view-b's replay window.
    const replay = await bridge.replay("s-multi", "view-b", -1);
    const recovered = replay.find((message) => message.kind === "event" && message.payload.name === "session.recovered");
    expect(recovered).toBeDefined();
    const nested = recovered?.payload as { data?: { replay?: Array<{ kind: string; payload: { name?: string } }> } };
    const replayedEvents = nested?.data?.replay ?? [];
    expect(replayedEvents.length).toBeGreaterThan(0);
    expect(replayedEvents.some((event) => event.kind === "event" && event.payload.name === "session.attached")).toBe(true);
  }, 30_000);
});
