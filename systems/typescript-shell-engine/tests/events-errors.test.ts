import { describe, it, expect, vi } from "vitest";
import { TypedEventEmitter } from "../src/engine/engine-events.ts";
import { ProtocolError, withRetry } from "../src/engine/protocol-errors.ts";

describe("TypedEventEmitter", () => {
  it("delivers payloads to subscribers", async () => {
    const ee = new TypedEventEmitter();
    const seen: string[] = [];
    ee.on("ack", ({ sessionId, ackSeq }) => { seen.push(`${sessionId}:${ackSeq}`); });
    await ee.emit("ack", { sessionId: "s1", ackSeq: 3 });
    expect(seen).toEqual(["s1:3"]);
  });

  it("unsubscribe stops delivery", async () => {
    const ee = new TypedEventEmitter();
    let count = 0;
    const off = ee.on("ack", () => { count += 1; });
    await ee.emit("ack", { sessionId: "s", ackSeq: 1 });
    off();
    await ee.emit("ack", { sessionId: "s", ackSeq: 2 });
    expect(count).toBe(1);
  });

  it("once fires exactly one time", async () => {
    const ee = new TypedEventEmitter();
    let count = 0;
    ee.once("session:attach", () => { count += 1; });
    await ee.emit("session:attach", { sessionId: "s", viewId: "v" });
    await ee.emit("session:attach", { sessionId: "s", viewId: "v" });
    expect(count).toBe(1);
  });

  it("off removes a specific listener only", async () => {
    const ee = new TypedEventEmitter();
    const hits: string[] = [];
    const l1 = () => hits.push("l1");
    const l2 = () => hits.push("l2");
    ee.on("error", l1);
    ee.on("error", l2);
    ee.off("error", l1);
    await ee.emit("error", { code: "X", message: "m" });
    expect(hits).toEqual(["l2"]);
  });

  it("emit on event with no listeners is a no-op", async () => {
    const ee = new TypedEventEmitter();
    await expect(ee.emit("transport:close", {})).resolves.toBeUndefined();
  });

  it("isolates listener errors without breaking others", async () => {
    const ee = new TypedEventEmitter();
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let reached = false;
    ee.on("health:change", () => { throw new Error("listener boom"); });
    ee.on("health:change", () => { reached = true; });
    await ee.emit("health:change", { healthy: true, latencyMs: 5 });
    expect(reached).toBe(true);
    expect(errSpy).toHaveBeenCalledOnce();
    errSpy.mockRestore();
  });

  it("awaits async listeners in order", async () => {
    const ee = new TypedEventEmitter();
    const order: number[] = [];
    ee.on("ack", async () => { await new Promise((r) => setTimeout(r, 5)); order.push(1); });
    ee.on("ack", () => { order.push(2); });
    await ee.emit("ack", { sessionId: "s", ackSeq: 9 });
    expect(order).toEqual([1, 2]);
  });

  it("removeAll clears every subscription", async () => {
    const ee = new TypedEventEmitter();
    let count = 0;
    ee.on("ack", () => { count += 1; });
    ee.on("error", () => { count += 1; });
    ee.removeAll();
    await ee.emit("ack", { sessionId: "s", ackSeq: 0 });
    await ee.emit("error", { code: "X", message: "m" });
    expect(count).toBe(0);
  });
});

describe("ProtocolError", () => {
  it("carries code, message and default non-retryable flag", () => {
    const err = new ProtocolError("VALIDATION_FAILED", "bad envelope");
    expect(err.code).toBe("VALIDATION_FAILED");
    expect(err.message).toBe("bad envelope");
    expect(err.retryable).toBe(false);
    expect(err instanceof Error).toBe(true);
    expect(err instanceof ProtocolError).toBe(true);
  });

  it("supports retryable flag and cause chain", () => {
    const cause = new Error("root cause");
    const err = new ProtocolError("TRANSPORT_TIMEOUT", "timed out", { retryable: true, cause });
    expect(err.retryable).toBe(true);
    expect(err.cause).toBe(cause);
  });

  it("serializes via toJSON for wire transport", () => {
    const err = new ProtocolError("SHARED_FILE_GATE", "register first", { retryable: true });
    expect(err.toJSON()).toEqual({ code: "SHARED_FILE_GATE", message: "register first", retryable: true });
  });

  it("covers all gate error codes as distinct values", () => {
    const codes = ["VALIDATION_FAILED", "TRANSPORT_CLOSED", "TRANSPORT_TIMEOUT",
      "SCOPE_NOT_REGISTERED", "TYPE_CONTENT_MISMATCH", "COAUTH_REJECTED",
      "SHARED_FILE_GATE", "BRIDGE_UNAVAILABLE"];
    for (const code of codes) {
      const err = new ProtocolError(code as never, "x");
      expect(err.code).toBe(code);
    }
  });
});

describe("withRetry", () => {
  it("returns immediately on success", async () => {
    let calls = 0;
    const result = await withRetry(async () => { calls += 1; return "ok"; }, { baseDelayMs: 1 });
    expect(result).toBe("ok");
    expect(calls).toBe(1);
  });

  it("retries retryable failures then succeeds", async () => {
    let calls = 0;
    const result = await withRetry(
      async () => {
        calls += 1;
        if (calls < 3) throw new ProtocolError("TRANSPORT_TIMEOUT", "flaky", { retryable: true });
        return "recovered";
      },
      { maxRetries: 3, baseDelayMs: 1 },
    );
    expect(result).toBe("recovered");
    expect(calls).toBe(3);
  });

  it("throws immediately on non-retryable ProtocolError", async () => {
    let calls = 0;
    await expect(withRetry(async () => {
      calls += 1;
      throw new ProtocolError("COAUTH_REJECTED", "no evidence");
    }, { maxRetries: 5, baseDelayMs: 1 })).rejects.toThrow("no evidence");
    expect(calls).toBe(1);
  });

  it("exhausts retries on plain errors and rethrows last", async () => {
    let calls = 0;
    await expect(withRetry(async () => {
      calls += 1;
      throw new Error(`fail ${calls}`);
    }, { maxRetries: 2, baseDelayMs: 1 })).rejects.toThrow("fail 3");
    expect(calls).toBe(3); // initial + 2 retries
  });

  it("aborts before attempt when signal already fired", async () => {
    const controller = new AbortController();
    controller.abort();
    let calls = 0;
    await expect(withRetry(async () => { calls += 1; return "x"; },
      { signal: controller.signal })).rejects.toBeInstanceOf(ProtocolError);
    expect(calls).toBe(0);
  });
});
