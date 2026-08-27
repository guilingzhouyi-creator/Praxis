import { describe, it, expect, vi } from "vitest";
import { MiddlewareChain } from "../src/engine/command-middleware.ts";
import { Dispatcher } from "../src/engine/dispatcher.ts";

describe("MiddlewareChain", () => {
  it("runs before FIFO and short-circuits", async () => {
    const chain = new MiddlewareChain();
    const order: string[] = [];
    chain.useBefore(() => { order.push("first"); return undefined; });
    chain.useBefore(() => { order.push("second"); return { kind: "local", data: { blocked: true } }; });
    // FIFO: first runs, then second short-circuits
    const res = await chain.runBefore({ command: { name: "x", args: [] }, ctx: { sessionId: "s" } });
    expect(res).toEqual({ kind: "local", data: { blocked: true } });
    expect(order).toEqual(["first", "second"]);
  });

  it("runs after FIFO and isolates errors", async () => {
    const chain = new MiddlewareChain();
    const order: string[] = [];
    chain.useAfter(() => order.push("a"));
    chain.useAfter(() => { throw new Error("boom"); });
    chain.useAfter(() => order.push("c"));
    await chain.runAfter({ command: { name: "x", args: [] }, ctx: { sessionId: "s" } }, { kind: "local", data: {} });
    expect(order).toEqual(["a", "c"]);
  });

  it("supports async after hooks", async () => {
    const chain = new MiddlewareChain();
    let done = false;
    chain.useAfter(async () => { await new Promise((r) => setTimeout(r, 5)); done = true; });
    await chain.runAfter({ command: { name: "x", args: [] }, ctx: { sessionId: "s" } }, { kind: "bridge", command: "x", args: [] });
    expect(done).toBe(true);
  });

  it("clear and size", () => {
    const chain = new MiddlewareChain();
    chain.useBefore(() => undefined);
    chain.useAfter(() => {});
    expect(chain.size).toBe(2);
    chain.clear();
    expect(chain.size).toBe(0);
  });

  it("integrates with Dispatcher (before short-circuit + after)", async () => {
    const dispatcher = new Dispatcher();
    const chain = new MiddlewareChain();
    dispatcher.useMiddleware(chain);
    dispatcher.register("ok", () => ({ kind: "local", data: { ok: 1 } }));

    chain.useBefore((ctx) => {
      if (ctx.command.name === "blocked") return { kind: "local", data: { blocked: 1 } };
      return undefined;
    });
    const after = vi.fn();
    chain.useAfter(after);

    expect(await dispatcher.dispatch({ name: "blocked", args: [] }, { sessionId: "s" })).toEqual({
      kind: "local",
      data: { blocked: 1 },
    });
    expect(after).toHaveBeenCalledTimes(1);

    after.mockClear();
    expect(await dispatcher.dispatch({ name: "ok", args: [] }, { sessionId: "s" })).toEqual({
      kind: "local",
      data: { ok: 1 },
    });
    expect(after).toHaveBeenCalledTimes(1);
  });
});
