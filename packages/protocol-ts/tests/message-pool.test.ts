import { describe, it, expect } from "vitest";
import { MessagePool } from "../src/engine/message-pool.ts";

describe("MessagePool", () => {
  it("validates size", () => {
    expect(() => new MessagePool(0)).toThrow();
  });

  it("acquire returns reset message with correct fields", () => {
    const pool = new MessagePool(2);
    const msg = pool.acquire("s-1", 42, "stream_chunk", "t-1");
    expect(msg.session_id).toBe("s-1");
    expect(msg.seq).toBe(42);
    expect(msg.kind).toBe("stream_chunk");
    expect(msg.trace_id).toBe("t-1");
    expect(msg.payload).toEqual({});
  });

  it("reuses after release and clears payload/trace", () => {
    const pool = new MessagePool(1);
    const m1 = pool.acquire("s-1", 1, "stream_chunk", "t");
    (m1.payload as any).data = "leak";
    pool.release(m1);
    const m2 = pool.acquire("s-1", 2, "stream_chunk", "");
    // reused instance, payload cleared
    expect(m2.payload).toEqual({});
    expect(m2.trace_id).toBe("");
    expect(pool.stats().pooled).toBe(0);
  });

  it("caps on release", () => {
    const pool = new MessagePool(1);
    const a = pool.acquire("s", 1);
    const b = pool.acquire("s", 2); // pool exhausted -> fresh
    expect(pool.stats().pooled).toBe(0);
    pool.release(a);
    pool.release(b); // second release exceeds cap, dropped
    expect(pool.stats().pooled).toBe(1);
  });

  it("stats tracks pooled", () => {
    const pool = new MessagePool(2);
    expect(pool.stats().pooled).toBe(2);
    pool.acquire("s", 1);
    expect(pool.stats().pooled).toBe(1);
  });
});
