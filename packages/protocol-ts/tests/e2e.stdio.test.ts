/**
 * Real end-to-end: TS bridge over the stdio transport against the actual
 * Python3 ProtocolHost (python -m l2.protocol), proving the protocol v1
 * contract round-trips across languages.
 *
 * Python3 path is overridable via PRAXIS_PYTHON; the host runs from the
 * repo src/ directory so `l2` and `l3` packages resolve on sys.path.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ProtocolBridge } from "../src/engine/bridge.ts";
import {
  createConfiguredHostTransport,
  resolveHostImplementation,
  type ManagedHostTransport,
} from "../src/engine/transports/rust-host.ts";

describe("e2e stdio host", () => {
  let managed: ManagedHostTransport;
  let bridge: ProtocolBridge;

  beforeAll(() => {
    managed = createConfiguredHostTransport({ timeoutMs: 30000 });
    bridge = new ProtocolBridge({ sessionId: "s-e2e", transport: managed });
  }, 30000);

  afterAll(() => {
    managed.close();
  });

  it("round-trips a command through the selected protocol host", async () => {
    const responses = await bridge.command("lang");
    const result = responses.find((message) => message.kind === "result");
    expect(result).toBeDefined();
    expect(typeof result?.payload.success).toBe("boolean");
    if (resolveHostImplementation() === "python") expect(result?.payload.success).toBe(true);
  }, 30000);

  it("attaches a view and keeps the response boundary intact", async () => {
    const attached = await bridge.attach("s-e2e", "view-e2e");
    expect(attached.some((message) => message.kind === "ack")).toBe(true);
    if (resolveHostImplementation() === "python") {
      expect(attached.some((message) => message.kind === "event" && message.payload.name === "session.attached")).toBe(true);
    }

    const replay = await bridge.replay("s-e2e", "view-e2e");
    expect(replay.some((message) => message.kind === "ack")).toBe(true);
  }, 30000);
});
