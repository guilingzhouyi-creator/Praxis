/** TS engine smoke tests: parser, dispatcher, and the protocol bridge client. */

import { describe, expect, it } from "vitest";
import { decodeMessage, encodeMessage, makeMessage, type Message } from "../src/envelope.ts";
import { parseLine, tokenize } from "../src/engine/parser.ts";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { ProtocolBridge, type Transport } from "../src/engine/bridge.ts";

describe("parser", () => {
  it("tokenizes with double-quote grouping", () => {
    expect(tokenize('say "hello world" ok')).toEqual(["say", "hello world", "ok"]);
  });

  it("splits a line into command name and args", () => {
    expect(parseLine("/status -v")).toEqual({ name: "/status", args: ["-v"] });
  });

  it("handles blank input", () => {
    expect(parseLine("   ")).toEqual({ name: "", args: [] });
  });
});

describe("dispatcher", () => {
  it("routes registered commands to local handlers", () => {
    const dispatcher = new Dispatcher();
    dispatcher.register("lang", () => ({ kind: "local", data: { lang: "en" } }));
    const result = dispatcher.dispatch({ name: "lang", args: [] }, { sessionId: "s-1" });
    expect(result).toEqual({ kind: "local", data: { lang: "en" } });
  });

  it("falls unknown commands back to the bridge", () => {
    const dispatcher = new Dispatcher();
    const result = dispatcher.dispatch({ name: "memory", args: ["digest"] }, { sessionId: "s-1" });
    expect(result).toEqual({ kind: "bridge", command: "memory", args: ["digest"] });
  });
});

/** Minimal fake Python3 host: answers commands with a result, control with an event. */
function fakeHost(received: string[]): Transport {
  return async (line: string) => {
    received.push(line);
    const decoded = decodeMessage(line);
    const message = decoded.message;
    if (!message) return [];
    if (message.kind === "command") {
      return [
        encodeMessage(makeMessage(message.session_id, 100, "result", { success: true, name: String(message.payload.name) })),
      ];
    }
    if (message.kind === "control") {
      return [
        encodeMessage(makeMessage(message.session_id, 101, "event", { name: `session.${String(message.payload.op)}`, data: {} })),
      ];
    }
    return [];
  };
}

describe("ProtocolBridge", () => {
  it("sends a command envelope and decodes the host result", async () => {
    const received: string[] = [];
    const bridge = new ProtocolBridge({ sessionId: "s-1", transport: fakeHost(received) });
    const responses = await bridge.command("lang", ["-v"]);
    expect(responses).toHaveLength(1);
    expect(responses[0].kind).toBe("result");
    expect(responses[0].payload.success).toBe(true);

    const outgoing = decodeMessage(received[0]).message;
    expect(outgoing?.kind).toBe("command");
    expect(outgoing?.payload.name).toBe("lang");
    expect(outgoing?.payload.args).toEqual(["-v"]);
  });

  it("emits attach control with an optional view id", async () => {
    const received: string[] = [];
    const bridge = new ProtocolBridge({ sessionId: "s-1", transport: fakeHost(received) });
    await bridge.attach("s-9", "v-1");
    const outgoing = decodeMessage(received[0]).message;
    expect(outgoing?.kind).toBe("control");
    expect(outgoing?.payload.op).toBe("attach");
    expect(outgoing?.payload.view_id).toBe("v-1");
  });

  it("acks per view and requests replays from a cursor", async () => {
    const received: string[] = [];
    const bridge = new ProtocolBridge({ sessionId: "s-1", transport: fakeHost(received) });
    await bridge.ack(5, "v-1");
    expect(decodeMessage(received[0]).message?.payload).toMatchObject({ ack_seq: 5, view_id: "v-1" });
    await bridge.replay("s-9", "v-1", 3);
    expect(decodeMessage(received[1]).message?.payload).toMatchObject({
      op: "recovery",
      session_id: "s-9",
      last_acked: 3,
      view_id: "v-1",
    });
  });
});
