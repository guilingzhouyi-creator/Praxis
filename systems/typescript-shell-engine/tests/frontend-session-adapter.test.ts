/**
 * FrontendSessionAdapter tests — lifecycle composition without a concrete UI.
 */

import { describe, expect, it } from "vitest";
import { decodeMessage, encodeMessage, makeMessage, type Message } from "../src/protocol/wire-envelope.ts";
import { ProtocolBridge, type Transport } from "../src/engine/bridge.ts";
import {
  FRONTEND_KINDS,
  FrontendSessionAdapter,
} from "../src/engine/frontend-session-adapter.ts";

function host(received: string[]): Transport {
  return async (line: string) => {
    received.push(line);
    const message = decodeMessage(line).message;
    if (!message) return [];
    if (message.kind === "control" && message.payload.op === "attach") {
      return [
        encodeMessage(
          makeMessage(message.session_id, 10, "event", {
            name: "session.attached",
            data: { session_id: message.payload.session_id, role: "operator", cell_id: "cell-a" },
          }),
        ),
      ];
    }
    if (message.kind === "control" && message.payload.op === "recovery") {
      return [
        encodeMessage(makeMessage(message.session_id, 11, "event", { name: "task.started" })),
        encodeMessage(makeMessage(message.session_id, 12, "result", { success: true, output: "ready" })),
      ];
    }
    if (message.kind === "ack") {
      return [encodeMessage(makeMessage(message.session_id, message.seq, "ack", { ack_seq: message.payload.ack_seq }))];
    }
    if (message.kind === "control" && message.payload.op === "detach") return [];
    if (message.kind === "command") {
      const name = typeof message.payload.name === "string" ? message.payload.name : "";
      const payload: Record<string, unknown> = name === "__system"
        ? { success: true, type: "system", output: "ok", stderr: "", returncode: 0 }
        : { success: true, name };
      return [encodeMessage(makeMessage(message.session_id, message.seq, "result", payload))];
    }
    return [];
  };
}

describe("FrontendSessionAdapter", () => {
  it("exposes the five frontend identities and maps SSH to the TUI projection", () => {
    expect(FRONTEND_KINDS).toEqual(["web", "tui", "desktop", "vscode", "ssh"]);
  });

  it("attaches, replays, acknowledges and detaches without owning host state", async () => {
    const received: string[] = [];
    const bridge = new ProtocolBridge({ sessionId: "client-1", transport: host(received) });
    const adapter = new FrontendSessionAdapter({
      bridge,
      sessionId: "session-9",
      viewId: "view-ssh",
      frontend: "ssh",
    });

    await expect(adapter.sync()).rejects.toThrow("not attached");
    const attached = await adapter.attach();
    expect(attached).toMatchObject({
      frontend: "ssh",
      session_id: "session-9",
      view_id: "view-ssh",
      identity: { role: "operator", cell_id: "cell-a" },
      projection: { frontend: "tui", session_id: "session-9" },
    });
    expect((attached.projection as { rows: unknown[] }).rows).toHaveLength(2);

    await adapter.ack(12);
    expect(adapter.localSnapshot().last_acked).toBe(12);
    await adapter.detach();
    await adapter.detach();
    expect(decodeMessage(received[2]).message).toMatchObject({
      kind: "ack",
      payload: { ack_seq: 12, view_id: "view-ssh" },
    });
    expect(decodeMessage(received[3]).message).toMatchObject({
      kind: "control",
      payload: { op: "detach", session_id: "session-9", view_id: "view-ssh" },
    });
  });

  it("composes TerminalShell and TerminalRenderer for one-line frontend submits", async () => {
    const bridge = new ProtocolBridge({ sessionId: "session-1", transport: host([]) });
    const adapter = new FrontendSessionAdapter({
      bridge,
      viewId: "view-tui",
      frontend: "tui",
    });

    const submitted = await adapter.submit("$ echo hello");
    expect(submitted).toMatchObject({
      frontend: "tui",
      input: "$ echo hello",
      run: { success: true, type: "bridge", route: { kind: "bridge", name: "__system" } },
    });
    expect(submitted.frame.lines.map((line) => line.text)).toEqual(["  ok", "[Exit] 0"]);
    expect(adapter.banner().type).toBe("banner");
  });
});
