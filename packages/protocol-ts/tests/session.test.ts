/**
 * End-to-end engine tests: session projection shapes, the SessionView
 * attach/replay/project flow over a fake host, and local builtins.
 */

import { describe, expect, it } from "vitest";
import { decodeMessage, encodeMessage, makeMessage, type Message } from "../src/envelope.ts";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { registerBuiltins } from "../src/engine/builtins.ts";
import { ProtocolBridge, type Transport } from "../src/engine/bridge.ts";
import { project, projectDesktop, projectTui, projectWeb, SessionView } from "../src/engine/session.ts";

const IDENTITY = { session_id: "s-1", terminal_id: "", process_id: "", role: "operator", cell_id: "cell-a" };
const EVENTS: Message[] = [
  makeMessage("s-1", 1, "event", { name: "session.attached" }, "", 0),
  makeMessage("s-1", 2, "result", { success: true, error: "" }, "", 0),
];

/** Fake host: answers attach with a session.attached event + identity, recovery with a replay. */
function sessionHost(received: string[]): Transport {
  return (line: string) => {
    received.push(line);
    const message = decodeMessage(line).message;
    if (!message) return [];
    if (message.kind === "command") {
      return [
        encodeMessage(
          makeMessage(message.session_id, 100, "result", { success: true, name: String(message.payload.name) }),
        ),
      ];
    }
    if (message.kind === "control") {
      if (message.payload.op === "attach") {
        const data = { session_id: message.payload.session_id, role: "operator", cell_id: "cell-a" };
        return [encodeMessage(makeMessage(message.session_id, 101, "event", { name: "session.attached", data }))];
      }
      if (message.payload.op === "recovery") {
        return [1, 2].map((seq) =>
          encodeMessage(makeMessage(message.session_id, seq, "event", { name: `replayed-${seq}` })),
        );
      }
    }
    return [];
  };
}

describe("session projection", () => {
  const state = { identity: IDENTITY, events: EVENTS };

  it("web shape passes the protocol through", () => {
    expect(projectWeb(state)).toEqual({ frontend: "web", session: IDENTITY, events: EVENTS });
  });

  it("tui shape renders table rows with summaries", () => {
    const out = projectTui(state);
    expect(out.headers).toEqual(["seq", "kind", "summary"]);
    expect(out.rows).toEqual([
      { seq: 1, kind: "event", summary: "session.attached" },
      // An empty error string mirrors the Python summarize fallback ("").
      { seq: 2, kind: "result", summary: "" },
    ]);
  });

  it("desktop shape renders rich-text blocks", () => {
    const out = projectDesktop(state);
    expect(out.blocks[0]).toMatchObject({ type: "heading", text: "Session s-1" });
    expect(out.blocks[1]).toMatchObject({ type: "text" });
    expect(out.blocks[2]).toMatchObject({ type: "event", seq: 1 });
  });

  it("unknown frontends fall back to web", () => {
    expect(project("ide-lsp", state).frontend).toBe("web");
  });
});

describe("SessionView end-to-end", () => {
  it("attaches, replays and projects through the bridge", () => {
    const received: string[] = [];
    const bridge = new ProtocolBridge({ sessionId: "s-1", transport: sessionHost(received) });
    const view = new SessionView("v-1", bridge);

    const identity = view.attach("s-9");
    expect(identity.role).toBe("operator");

    const state = view.state("s-9");
    expect(state.events).toHaveLength(2);
    expect(state.events[0].payload.name).toBe("replayed-1");

    const tui = project("tui", state);
    expect(tui.session_id).toBe("s-9");
    expect(tui.rows).toHaveLength(2);

    // The outgoing control carried the view id so the host can track it.
    expect(decodeMessage(received[0]).message?.payload.view_id).toBe("v-1");
    expect(decodeMessage(received[1]).message?.payload.op).toBe("recovery");
  });
});

describe("builtins", () => {
  it("registers local-only commands and lists them via help", () => {
    const dispatcher = new Dispatcher();
    registerBuiltins(dispatcher);
    expect(dispatcher.dispatch({ name: "lang", args: [] }, { sessionId: "s-1" })).toEqual({
      kind: "local",
      data: { lang: "en" },
    });
    expect(dispatcher.dispatch({ name: "help", args: [] }, { sessionId: "s-1" })).toEqual({
      kind: "local",
      data: { commands: ["clear", "help", "lang"] },
    });
    expect(dispatcher.dispatch({ name: "help", args: ["lang"] }, { sessionId: "s-1" })).toEqual({
      kind: "local",
      data: { command: "lang", registered: true },
    });
    expect(dispatcher.dispatch({ name: "clear", args: [] }, { sessionId: "s-1" }).kind).toBe("local");
  });

  it("still falls unknown commands back to the bridge", () => {
    const dispatcher = new Dispatcher();
    registerBuiltins(dispatcher);
    expect(dispatcher.dispatch({ name: "memory", args: ["digest"] }, { sessionId: "s-1" }).kind).toBe("bridge");
  });
});
