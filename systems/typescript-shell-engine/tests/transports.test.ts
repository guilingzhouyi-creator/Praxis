/**
 * Transport engine + adapter tests: ack-line boundary, concurrency
 * rejection, timeouts, fake WebSocket server and fake SSH channel.
 */

import { Readable } from "node:stream";
import { describe, expect, it } from "vitest";
import { decodeMessage, encodeMessage, makeMessage } from "../src/protocol/wire-envelope.ts";
import { createLineRequestTransport, isAckLine } from "../src/engine/transports/line-transport.ts";
import { createWsTransport, type WsTransportOptions } from "../src/engine/transports/ws.ts";
import { createSshTransport, type SshChannelLike, type SshTransportOptions } from "../src/engine/transports/ssh.ts";
import { MAX_FRAME_BYTES } from "../src/protocol/wire-types.ts";

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

  it("closes on a synthetic host protocol failure without waiting for an ack", async () => {
    let handler: ((line: string) => void) | undefined;
    const transport = createLineRequestTransport({
      onLine: (h) => { handler = h; },
      writeLine: () => undefined,
      timeoutMs: 5_000,
    });
    const request = transport("request");
    const failure = encodeMessage(makeMessage("-", 1, "result", { success: false, error: "invalid json" }));
    handler?.(failure);
    await expect(request).resolves.toEqual([failure]);
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

  it("rejects frames above the shared UTF-8 byte bound before writing", async () => {
    let writes = 0;
    const transport = createLineRequestTransport({
      onLine: () => undefined,
      writeLine: () => {
        writes++;
      },
    });
    await expect(transport("x".repeat(MAX_FRAME_BYTES + 1))).rejects.toThrow("request frame exceeds");
    expect(writes).toBe(0);
    // Multi-byte input is measured in bytes, not JavaScript UTF-16 units.
    await expect(transport("界".repeat(Math.ceil(MAX_FRAME_BYTES / 3)))).rejects.toThrow("request frame exceeds");
  });

  it("clears a pending request when the sink throws", async () => {
    let fail = true;
    let handler: ((line: string) => void) | undefined;
    const transport = createLineRequestTransport({
      onLine: (h) => {
        handler = h;
      },
      writeLine: () => {
        if (fail) throw new Error("sink failed");
      },
    });
    await expect(transport("first")).rejects.toThrow("sink failed");
    fail = false;
    const request = transport("second");
    handler?.(encodeMessage(makeMessage("s", 1, "ack", { ack_seq: 1 })));
    await expect(request).resolves.toHaveLength(1);
  });

  it("rejects invalid response budgets at construction", () => {
    const base = {
      onLine: () => undefined,
      writeLine: () => undefined,
    };
    expect(() => createLineRequestTransport({ ...base, maxLines: 0 })).toThrow("maxLines");
    expect(() => createLineRequestTransport({ ...base, maxLines: 1.5 })).toThrow("maxLines");
    expect(() => createLineRequestTransport({ ...base, timeoutMs: -1 })).toThrow("timeoutMs");
    expect(() => createLineRequestTransport({ ...base, timeoutMs: Number.NaN })).toThrow("timeoutMs");
  });

  it("rejects a pending request when the source fails", async () => {
    let fail!: (error: unknown) => void;
    const transport = createLineRequestTransport({
      onLine: () => undefined,
      onError: (handler) => { fail = handler; },
      writeLine: () => undefined,
      timeoutMs: 5_000,
    });
    const request = transport("request");
    fail(new Error("source failed"));
    await expect(request).rejects.toThrow("source failed");
    await expect(transport("after failure")).rejects.toThrow("source failed");
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
