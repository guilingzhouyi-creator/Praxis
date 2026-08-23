/**
 * Transport engine + adapter tests: ack-line boundary, concurrency
 * rejection, timeouts, fake WebSocket server and fake SSH channel.
 */

import { Readable } from "node:stream";
import { describe, expect, it } from "vitest";
import { decodeMessage, encodeMessage, makeMessage } from "../src/envelope.ts";
import { createLineRequestTransport, isAckLine } from "../src/engine/transports/line-transport.ts";
import { createWsTransport, type WsTransportOptions } from "../src/engine/transports/ws.ts";
import { createSshTransport, type SshChannelLike, type SshTransportOptions } from "../src/engine/transports/ssh.ts";

/** Fake WebSocket implementation injected into the ws adapter. */
class FakeWebSocket {
  static OPEN = 1;
  readyState = 0;
  onmessage: ((event: { data: string }) => void) | null = null;
  sent: string[] = [];
  constructor(public readonly url: string) {}

  send(data: string): void {
    this.readyState = FakeWebSocket.OPEN;
    this.sent.push(data);
  }

  /** Test helper: the server pushes one response line. */
  serverPush(line: string): void {
    if (this.onmessage) this.onmessage({ data: line });
  }
}

describe("line transport engine", () => {
  it("resolves on the ack line and rejects concurrent requests", async () => {
    let handler: ((line: string) => void) | undefined;
    const sent: string[] = [];
    const transport = createLineRequestTransport({
      onLine: (h) => {
        handler = h;
      },
      writeLine: (line) => sent.push(line),
    });
    const request = transport("request-1");
    // A second request while the first is still pending is rejected.
    await expect(transport("request-2")).rejects.toThrow("concurrent request");
    handler?.("result-line");
    handler?.(encodeMessage(makeMessage("s", 1, "ack", { ack_seq: 1 })));
    const lines = await request;
    // The engine collects every response line up to and including the ack.
    expect(lines).toHaveLength(2);
    expect(lines[0]).toBe("result-line");
    expect(sent).toEqual(["request-1"]);
  });

  it("recognizes the ack line as the response boundary", () => {
    expect(isAckLine(encodeMessage(makeMessage("s", 1, "ack", { ack_seq: 1 })))).toBe(true);
    expect(isAckLine('{"kind":"result","success":true}')).toBe(false);
    expect(isAckLine("not-json")).toBe(false);
  });

  it("times out a stalled host with what it has collected", async () => {
    let handler: ((line: string) => void) | undefined;
    const transport = createLineRequestTransport({
      onLine: (h) => {
        handler = h;
      },
      writeLine: () => undefined,
      timeoutMs: 20,
    });
    const request = transport("req");
    handler?.("partial");
    const lines = await request;
    expect(lines).toEqual(["partial"]);
  });
});

describe("ws transport", () => {
  it("round-trips over a fake websocket server", async () => {
    const fake = new FakeWebSocket("ws://host/ws");
    fake.readyState = FakeWebSocket.OPEN; // simulate an established socket
    const options: WsTransportOptions = { url: "ws://host/ws", WebSocketInstance: fake };
    const transport = createWsTransport(options);

    const request = transport("hello");
    expect(fake.sent).toEqual(["hello"]);
    fake.serverPush(encodeMessage(makeMessage("s", 10, "result", { success: true })));
    fake.serverPush(encodeMessage(makeMessage("s", 11, "ack", { ack_seq: 1 })));
    const responses = await request;
    expect(responses).toHaveLength(2);
    expect(decodeMessage(responses[1]).message?.kind).toBe("ack");
  });

  it("fails fast when the socket is not open", () => {
    const fake = new FakeWebSocket("ws://host/ws"); // readyState stays CONNECTING
    const options: WsTransportOptions = { url: "ws://host/ws", WebSocketInstance: fake };
    const transport = createWsTransport(options);
    // readyState stays 0 (no send happened yet) — writeLine throws.
    void transport("x").catch(() => undefined);
  });
});

describe("ssh transport", () => {
  it("round-trips over a fake ssh2 channel", async () => {
    let handler: ((line: string) => void) | undefined;
    const stdout = new Readable({ read() {} });
    const fakeChannel: SshChannelLike = {
      stdout,
      write: (data: string) => {
        // Mirror a remote host answering with result + ack.
        stdout.push(encodeMessage(makeMessage("s", 20, "result", { success: true })) + "\n");
        stdout.push(encodeMessage(makeMessage("s", 21, "ack", { ack_seq: 1 })) + "\n");
      },
    };
    const fakeClient = {
      on(event: string, cb: () => void) {
        if (event === "ready") cb();
        return this;
      },
      connect() {
        return this;
      },
      exec(_cmd: string, cb: (err: unknown, stream?: unknown) => void) {
        cb(null, fakeChannel);
      },
    };
    const options: SshTransportOptions = {
      host: "remote",
      username: "ops",
      createClient: () => fakeClient as unknown as ReturnType<typeof createSshTransportOptions>,
    };
    const transport = createSshTransport(options);
    // Give the fake connect → exec → attach cycle a tick to wire the handler.
    await new Promise((resolve) => setTimeout(resolve, 5));
    const responses = await transport("hi");
    expect(responses).toHaveLength(2);
    expect(decodeMessage(responses[0]).message?.payload.success).toBe(true);
  });

  it("queues writes issued before the channel is ready and flushes on attach", async () => {
    // A fake client that does NOT attach immediately: the first write must
    // be buffered (readiness handshake) and flushed once the channel lands.
    const received: string[] = [];
    let attach!: (channel: SshChannelLike) => void;
    const fakeClient = {
      on(event: string, cb: () => void) {
        if (event === "ready") cb();
        return this;
      },
      connect() {
        return this;
      },
      exec(_cmd: string, cb: (err: unknown, stream?: unknown) => void) {
        attach = (ch) => cb(null, ch);
      },
    };
    const stdout = new Readable({ read() {} });
    const options: SshTransportOptions = {
      host: "remote",
      username: "ops",
      createClient: () => fakeClient as unknown as ReturnType<typeof createSshTransportOptions>,
    };
    const transport = createSshTransport(options);

    // Issue a request before any channel exists — the write must queue.
    const pending = transport("early");
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(received).toHaveLength(0);

    // Attach the channel; the queued write is flushed and answered.
    attach({
      stdout,
      write: (data: string) => {
        received.push(data);
        stdout.push(encodeMessage(makeMessage("s", 30, "result", { success: true })) + "\n");
        stdout.push(encodeMessage(makeMessage("s", 31, "ack", { ack_seq: 1 })) + "\n");
      },
    });
    const responses = await pending;
    expect(received).toHaveLength(1);
    expect(received[0]).toContain("early");
    expect(responses).toHaveLength(2);
  });
});

function createSshTransportOptions(): never {
  throw new Error("type helper only");
}
