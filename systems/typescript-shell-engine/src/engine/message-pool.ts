/**
 * MessagePool — preallocated Message factory with reset-and-reuse.
 *
 * In high-throughput sessions (stream_chunk at 10K+/sec), allocating a new
 * object per envelope causes GC pressure. This pool preallocates a fixed set
 * of mutable objects and resets their fields on acquire, eliminating GC cost.
 *
 * Only used when the consumer guarantees no long-lived references to pooled
 * messages (stream_chunk data flows through and is discarded).
 *
 * NOT for: ack/control/result messages that are stored in Outbox or replayed.
 * Those MUST be freshly allocated because they persist beyond the current
 * microtask. Use the regular makeMessage() for those.
 */

import { PROTOCOL_VERSION, type MessageKind } from "../wire-types.ts";
import type { Message } from "../wire-envelope.ts";

/** Internal pooled shape — `_pooled` is stripped before crossing the wire. */
interface PoolableMessage extends Message {
  _pooled: true;
}

/**
 * Bounded pool for high-frequency `stream_chunk` envelopes.
 *
 * Reusing the same objects eliminates GC pressure at 10K+/sec; callers
 * MUST `release()` after the microtask and MUST NOT retain pooled
 * messages in `Outbox`/replay. Persistent messages use `makeMessage()`.
 */
export class MessagePool {
  private pool: PoolableMessage[] = [];

  constructor(private readonly size = 64) {
    if (!Number.isInteger(size) || size < 1) throw new Error("size must be a positive integer");
    for (let i = 0; i < size; i++) {
      this.pool.push({
        v: PROTOCOL_VERSION,
        session_id: "",
        seq: 0,
        ts: 0,
        trace_id: "",
        kind: "stream_chunk" as MessageKind,
        payload: {},
        _pooled: true,
      } as PoolableMessage);
    }
  }

  /** Acquire a reset message; caller owns it until `release()`. */
  acquire(sessionId: string, seq: number, kind: MessageKind = "stream_chunk", traceId = ""): PoolableMessage {
    const msg = this.pool.pop() ??
      ({
        v: PROTOCOL_VERSION,
        session_id: "",
        seq: 0,
        ts: 0,
        trace_id: "",
        kind: "stream_chunk" as MessageKind,
        payload: {},
        _pooled: true as const,
      } as PoolableMessage);
    this.fill(msg, sessionId, seq, kind, traceId);
    return msg;
  }

  /** Return a message to the pool; clears payload to avoid retaining data. */
  release(msg: PoolableMessage): void {
    if (this.pool.length < this.size) {
      msg.payload = {};
      msg.trace_id = "";
      this.pool.push(msg);
    }
  }

  /** Current pooled count (bench/telemetry). */
  stats(): { pooled: number } {
    return { pooled: this.pool.length };
  }

  /** Top up the pool with reset messages. */
  private fill(
    msg: PoolableMessage,
    sessionId: string, seq: number, kind: string, traceId: string,
  ): void {
    msg.v = PROTOCOL_VERSION;
    msg.session_id = sessionId;
    msg.seq = seq;
    msg.ts = Date.now() / 1000;
    msg.trace_id = traceId;
    msg.kind = kind as MessageKind;
    msg.payload = {};
  }
}
