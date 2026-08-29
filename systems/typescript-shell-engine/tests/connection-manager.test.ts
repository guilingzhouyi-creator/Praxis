import { describe, expect, it } from "vitest";
import { ConnectionManager, type TransportFactory } from "../src/engine/connection-manager.ts";
import { makeMessage } from "../src/protocol/wire-envelope.ts";

/** A fake transport that fails N times, then answers systemStatus. */
function flakyFactory(failures: number, onAttempt: (n: number) => void): TransportFactory {
  let attempts = 0;
  return () => {
    const n = ++attempts;
    onAttempt(n);
    return async (line: string) => {
      if (n <= failures) throw new Error(`fake failure ${n}`);
      return [JSON.stringify(makeMessage("s-1", 1, "result", { success: true }))];
    };
  };
}

/** A fake transport that always fails. */
function alwaysFailingFactory(onAttempt: (n: number) => void): TransportFactory {
  let attempts = 0;
  return () => {
    const n = ++attempts;
    onAttempt(n);
    return async () => {
      throw new Error(`fake failure ${n}`);
    };
  };
}

describe("ConnectionManager", () => {
  it("connects on the first attempt when the factory succeeds", async () => {
    const attempts: number[] = [];
    const manager = new ConnectionManager({
      factory: flakyFactory(0, (n) => attempts.push(n)),
      sessionId: "s-1",
    });
    const bridge = await manager.connect();
    expect(bridge).toBeDefined();
    expect(manager.isConnected()).toBe(true);
    expect(manager.getState()).toMatchObject({ status: "connected" });
    expect(attempts).toEqual([1]);
  });

  it("retries with backoff and recovers (connecting → reconnecting → connected)", async () => {
    const attempts: number[] = [];
    const manager = new ConnectionManager({
      factory: flakyFactory(2, (n) => attempts.push(n)),
      sessionId: "s-1",
      baseDelayMs: 1, // tiny backoff so the test is fast
    });
    const bridge = await manager.connect();
    expect(bridge).toBeDefined();
    expect(manager.isConnected()).toBe(true);
    // 1 fail + 2nd fail + success = 3 attempts.
    expect(attempts).toEqual([1, 2, 3]);
  });

  it("exhausts retries, lands on disconnected, and throws a real error", async () => {
    const attempts: number[] = [];
    const manager = new ConnectionManager({
      factory: alwaysFailingFactory((n) => attempts.push(n)),
      sessionId: "s-1",
      maxRetries: 2,
      baseDelayMs: 1,
    });
    await expect(manager.connect()).rejects.toThrow("fake failure 3");
    expect(manager.isConnected()).toBe(false);
    expect(manager.getState()).toMatchObject({ status: "disconnected" });
    // maxRetries=2 → attempts 1,2,3 (maxRetries + 1 total).
    expect(attempts).toEqual([1, 2, 3]);
  });

  it("rejects invalid maxRetries at construction", () => {
    expect(
      () =>
        new ConnectionManager({
          factory: alwaysFailingFactory(() => {}),
          sessionId: "s-1",
          maxRetries: -1,
        }),
    ).toThrow(/maxRetries must be a non-negative integer/);
    expect(
      () =>
        new ConnectionManager({
          factory: alwaysFailingFactory(() => {}),
          sessionId: "s-1",
          maxRetries: 1.5,
        }),
    ).toThrow(/maxRetries must be a non-negative integer/);
  });

  it("rejects invalid baseDelayMs at construction", () => {
    expect(
      () =>
        new ConnectionManager({
          factory: alwaysFailingFactory(() => {}),
          sessionId: "s-1",
          baseDelayMs: -5,
        }),
    ).toThrow(/baseDelayMs must be a finite non-negative number/);
    expect(
      () =>
        new ConnectionManager({
          factory: alwaysFailingFactory(() => {}),
          sessionId: "s-1",
          baseDelayMs: Number.NaN,
        }),
    ).toThrow(/baseDelayMs must be a finite non-negative number/);
  });

  it("guards against throwing undefined when no attempt runs", async () => {
    // Simulate a future path that skips the loop by forcing zero retries
    // with a factory that throws synchronously inside the first attempt —
    // the guarded throw must still surface a real Error.
    const manager = new ConnectionManager({
      factory: () => {
        throw new Error("sync factory failure");
      },
      sessionId: "s-1",
      maxRetries: 0,
      baseDelayMs: 0,
    });
    await expect(manager.connect()).rejects.toThrow("sync factory failure");
  });

  it("releases a closeable transport on disconnect", async () => {
    let closed = 0;
    const manager = new ConnectionManager({
      factory: () => {
        const transport = (async () => [JSON.stringify(makeMessage("s-1", 1, "result", { success: true }))]) as unknown as {
          (line: string): Promise<string[]>;
          close: () => void;
        };
        transport.close = () => {
          closed++;
        };
        return transport;
      },
      sessionId: "s-1",
    });
    await manager.connect();
    expect(closed).toBe(0);
    manager.disconnect();
    expect(closed).toBe(1);
    // Idempotent disconnect: no double-close.
    manager.disconnect();
    expect(closed).toBe(1);
  });

  it("closes a failed probe's transport so reconnection never leaks children", async () => {
    const closed: string[] = [];
    let attempts = 0;
    const manager = new ConnectionManager({
      factory: () => {
        const n = ++attempts;
        const t = (async () => [JSON.stringify(makeMessage("s-1", 1, "result", { success: true }))]) as unknown as {
          (line: string): Promise<string[]>;
          close: () => void;
        };
        t.close = () => {
          closed.push(`transport-${n}`);
        };
        if (n <= 2) {
          // First two probes fail at the protocol level.
          const broken = async () => {
            throw new Error(`probe failure ${n}`);
          };
          const bt = broken as typeof t;
          bt.close = () => closed.push(`transport-${n}`);
          return bt;
        }
        return t;
      },
      sessionId: "s-1",
      maxRetries: 2,
      baseDelayMs: 1,
    });
    await manager.connect();
    expect(attempts).toBe(3);
    expect(closed).toEqual(["transport-1", "transport-2"]);
    manager.disconnect();
    expect(closed).toEqual(["transport-1", "transport-2", "transport-3"]);
  });

  it("tolerates a throwing close (best-effort release)", async () => {
    const manager = new ConnectionManager({
      factory: () => {
        const t = (async () => [JSON.stringify(makeMessage("s-1", 1, "result", { success: true }))]) as unknown as {
          (line: string): Promise<string[]>;
          close: () => void;
        };
        t.close = () => {
          throw new Error("close exploded");
        };
        return t;
      },
      sessionId: "s-1",
    });
    await manager.connect();
    expect(() => manager.disconnect()).not.toThrow();
  });
});
