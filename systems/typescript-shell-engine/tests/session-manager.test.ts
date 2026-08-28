/**
 * SessionManager tests: multi-view multiplexing, per-view non-destructive
 * ack, shared watermark = lagging view, and bridge round-trips.
 */

import { describe, expect, it } from "vitest";
import { encodeMessage, makeMessage, type Message } from "../src/wire-envelope.ts";
import { ProtocolBridge, type Transport } from "../src/engine/bridge.ts";
import { SessionManager, SessionMultiplexer } from "../src/engine/session-manager.ts";

describe("SessionMultiplexer", () => {
  it("delivers emitted events to every bound view", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.attach("web");
    mux.attach("tui");
    mux.emit(makeMessage("s-1", 1, "event", { name: "a" }));
    mux.emit(makeMessage("s-1", 2, "event", { name: "b" }));
    expect(mux.viewState("web")?.unacked).toHaveLength(2);
    expect(mux.viewState("tui")?.unacked).toHaveLength(2);
  });

  it("acks non-destructively per view; other views keep their windows", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.attach("web");
    mux.attach("tui");
    mux.emit(makeMessage("s-1", 1, "event", { name: "a" }));
    mux.emit(makeMessage("s-1", 2, "event", { name: "b" }));
    mux.ack("web", 1);
    // web acked seq 1, keeps seq 2; tui keeps both.
    expect(mux.viewState("web")?.unacked.map((e) => e.seq)).toEqual([2]);
    expect(mux.viewState("tui")?.unacked.map((e) => e.seq)).toEqual([1, 2]);
  });

  it("shared watermark follows the lagging view", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.attach("web");
    mux.attach("tui");
    mux.emit(makeMessage("s-1", 1, "event", { name: "a" }));
    mux.emit(makeMessage("s-1", 2, "event", { name: "b" }));
    mux.ack("web", 2); // web caught up
    expect(mux.watermark()).toBe(-1); // tui still at -1 → lagging
    mux.ack("tui", 2);
    expect(mux.watermark()).toBe(2);
  });

  it("replay rebuilds the window from the event stream", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.attach("web");
    mux.emit(makeMessage("s-1", 1, "event", { name: "a" }));
    mux.emit(makeMessage("s-1", 2, "event", { name: "b" }));
    const window = mux.replay("web", 1);
    expect(window.map((e) => e.seq)).toEqual([2]);
  });

  it("attach is idempotent and detach removes the view", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.attach("web");
    mux.attach("web");
    expect(mux.listViews()).toEqual(["web"]);
    mux.detach("web");
    expect(mux.listViews()).toEqual([]);
  });

  it("bounds the local mirror when a view remains stalled", () => {
    const mux = new SessionMultiplexer("s-1", { maxEvents: 2 });
    mux.attach("web");
    mux.emit(makeMessage("s-1", 1, "event", { name: "a" }));
    mux.emit(makeMessage("s-1", 2, "event", { name: "b" }));
    mux.emit(makeMessage("s-1", 3, "event", { name: "c" }));
    expect(mux.viewState("web")?.unacked.map((event) => event.seq)).toEqual([2, 3]);
    expect(mux.replay("web", -1).map((event) => event.seq)).toEqual([2, 3]);
  });

  it("releases acknowledged prefixes before retaining new events", () => {
    const mux = new SessionMultiplexer("s-1", { maxEvents: 2 });
    mux.attach("web");
    mux.emit(makeMessage("s-1", 1, "event", { name: "a" }));
    mux.emit(makeMessage("s-1", 2, "event", { name: "b" }));
    mux.ack("web", 2);
    mux.emit(makeMessage("s-1", 3, "event", { name: "c" }));
    expect(mux.replay("web", 2).map((event) => event.seq)).toEqual([3]);
  });

  it("keeps replay events ordered when an older host event arrives", () => {
    const mux = new SessionMultiplexer("s-1", { maxEvents: 2 });
    mux.attach("web");
    mux.emit(makeMessage("s-1", 2, "event", { name: "b" }));
    mux.emit(makeMessage("s-1", 3, "event", { name: "c" }));
    mux.emit(makeMessage("s-1", 1, "event", { name: "a" }));
    expect(mux.replay("web", -1).map((event) => event.seq)).toEqual([2, 3]);
  });

  it("rejects an invalid mirror capacity at construction", () => {
    expect(() => new SessionMultiplexer("s-1", { maxEvents: 0 })).toThrow(/safe integer >= 1/);
    expect(() => new SessionMultiplexer("s-1", { maxEvents: 1.5 })).toThrow(/safe integer >= 1/);
    expect(() => new SessionMultiplexer("s-1", { maxEvents: Number.MAX_SAFE_INTEGER + 1 })).toThrow(/safe integer >= 1/);
  });

  it("never mirrors ack messages into the replay stream", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.attach("web");
    mux.emit(makeMessage("s-1", 1, "ack", { ack_seq: 1 }));
    expect(mux.viewState("web")?.unacked).toHaveLength(0);
  });

  it("deduplicates identical events by key", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.attach("web");
    const event = makeMessage("s-1", 1, "event", { name: "a" });
    mux.emit(event);
    mux.emit(event);
    expect(mux.viewState("web")?.unacked).toHaveLength(1);
  });

  it("treats unknown views as no-ops and reports an empty watermark", () => {
    const mux = new SessionMultiplexer("s-1");
    mux.ack("ghost", 5);
    expect(mux.replay("ghost", 3)).toEqual([]);
    expect(mux.viewState("ghost")).toBeUndefined();
    expect(mux.watermark()).toBe(-1);
  });
});

describe("SessionManager over a fake bridge", () => {
  /** Fake host: answers attach/ack/replay with the expected control events. */
  function fakeBridge(received: string[]): ProtocolBridge {
    const transport: Transport = async (line) => {
      received.push(line);
      const decoded = JSON.parse(line) as Message;
      if (decoded.kind === "control") {
        if (decoded.payload.op === "attach") {
          return [
            encodeMessage(
              makeMessage(decoded.session_id, 100, "event", { name: "session.attached", data: { session_id: decoded.payload.session_id } }),
            ),
          ];
        }
        if (decoded.payload.op === "recovery") {
          return [encodeMessage(makeMessage(decoded.session_id, 101, "event", { name: "session.recovered", data: { session_id: decoded.payload.session_id } }))];
        }
      }
      return [];
    };
    return new ProtocolBridge({ sessionId: "s-1", transport });
  }

  it("attach round-trips and records the host's attached event", async () => {
    const received: string[] = [];
    const manager = new SessionManager(fakeBridge(received));
    const state = await manager.attach("s-9", "web");
    expect(state.viewId).toBe("web");
    expect(manager.listSessions()).toContain("s-9");
    expect(received[0]).toContain('"op":"attach"');
  });

  it("replay merges host recovery events into the local window", async () => {
    const manager = new SessionManager(fakeBridge([]));
    await manager.attach("s-9", "web");
    const events = await manager.replay("s-9", "web", -1);
    expect(events.some((e) => e.payload.name === "session.recovered")).toBe(true);
    expect(manager.watermark("s-9")).toBe(-1);
  });

  it("routes ack and recovery to the requested session without duplicating replay", async () => {
    const received: string[] = [];
    const manager = new SessionManager(fakeBridge(received));
    await manager.attach("s-a", "web");
    await manager.attach("s-b", "tui");
    await manager.ack("s-b", "tui", 3);
    const replay = await manager.replay("s-a", "web", -1);
    expect(replay.filter((message) => message.payload.name === "session.recovered")).toHaveLength(1);
    const requests = received.map((line) => JSON.parse(line) as { session_id: string; payload: Record<string, unknown> });
    expect(requests.map((request) => request.session_id)).toEqual(["s-a", "s-b", "s-b", "s-a"]);
    expect(requests[2].payload).toMatchObject({ ack_seq: 3, view_id: "tui" });
  });

  it("falls back to the merged local window when the host replies without events", async () => {
    // Attach answers with one event (populating the local mirror), while the
    // recovery control reply stays empty so hostEvents is empty.
    const quietTransport: Transport = async (line) => {
      const decoded = JSON.parse(line) as Message;
      if (decoded.kind === "control" && decoded.payload.op === "attach") {
        return [
          encodeMessage(
            makeMessage(decoded.session_id, 100, "event", { name: "session.attached", data: { session_id: decoded.payload.session_id } }),
          ),
        ];
      }
      return [];
    };
    const manager = new SessionManager(new ProtocolBridge({ sessionId: "s-1", transport: quietTransport }));
    await manager.attach("s-9", "web");
    const events = await manager.replay("s-9", "web", -1);
    expect(events.some((event) => event.payload.name === "session.attached")).toBe(true);
  });

  it("returns the local window unchanged when both host and mirror are empty", async () => {
    const silent = new ProtocolBridge({ sessionId: "s-1", transport: async () => [] });
    const manager = new SessionManager(silent);
    const events = await manager.replay("s-9", "web", -1);
    expect(events).toEqual([]);
    expect(manager.listSessions()).toContain("s-9");
  });

  it("detach drops the local mirror and forwards the control to the host", async () => {
    const received: string[] = [];
    const manager = new SessionManager(fakeBridge(received));
    await manager.attach("s-9", "web");
    expect(manager.listSessions()).toContain("s-9");

    await manager.detach("s-9", "web");
    expect(received[received.length - 1]).toContain('"op":"detach"');
    expect(received[received.length - 1]).toContain('"session_id":"s-9"');
    // Last view gone: the empty multiplexer is released from the registry.
    expect(manager.listSessions()).not.toContain("s-9");
  });

  it("detach keeps the session while other views are attached", async () => {
    const received: string[] = [];
    const manager = new SessionManager(fakeBridge(received));
    await manager.attach("s-9", "web");
    await manager.attach("s-9", "tui");
    await manager.detach("s-9", "web");
    expect(manager.listSessions()).toContain("s-9");
    expect(manager.watermark("s-9")).toBe(-1); // tui still attached
  });
});
