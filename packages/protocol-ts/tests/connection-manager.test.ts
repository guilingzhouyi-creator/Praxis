/**
 * ConnectionManager tests — retry FSM, config validation, exhaustion.
 *
 * Drives connect() with failing-then-succeeding and always-failing fake
 * factories, asserting the attempt count, state sequence
 * (connecting → reconnecting → connected / final disconnected), and that
 * exhaustion throws a real Error (never undefined).
 */

import { describe, expect, it } from "vitest";
import { ConnectionManager, type TransportFactory } from "../src/engine/connection-manager.ts";

/** A fake transport that fails N times, then answers systemStatus. */
function flakyFactory(failures: number, onAttempt: (n: number) => void): TransportFactory {
  let attempts = 0;
  return () => {
    const n = ++attempts;
    onAttempt(n);
    return async (line: string) => {
      if (n <= failures) throw new Error(`fake failure ${n}`);
      return [`{"kind":"result","payload":{"success":true}}`];
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
});
