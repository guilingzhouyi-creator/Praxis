/**
 * MessagePool — preallocated Message factory with reset-and-reuse.
 *
 * In high-throughput sessions (stream_chunk at 10K+/sec), allocating a new
 * object per envelope causes GC pressure. This pool preallocates a fixed set
 * of mutable objects and resets their fields on acquire, eliminating GC cost.
 *
 * TS pattern: `Object.assign` + `satisfies` operator for pool item shape.
 * Only used when the consumer guarantees no long-lived references to pooled
 * messages (stream_chunk data flows through and is discarded).
 *
 * NOT for: ack/control/result messages that are stored in Outbox or replayed.
 * Those MUST be freshly allocated because they persist beyond the current
 * microtask. Use the regular makeMessage() for those.
 */

import { PROTOCOL_VERSION } from "../types.ts";

interface PoolableMessage {
  v: typeof PROTOCOL_VERSION;
  session_id: string;
  seq: number;
  ts: number;
  trace_id: string;
  kind: string;
  payload: Record<string, unknown>;
  _pooled: true;
}

export class MessagePool {
  private pool: PoolableMessage[] = [];
  private allocated = 0;
  private reused = 0;

  constructor(private readonly size = 64) {
    for (let i = 0; i < size; i++) {
      this.pool.push({
        v: PROTOCOL_VERSION,
        session_id: "",
        seq: 0,
        ts: 0,
        trace_id: "",
        kind: "",
        payload: {},
        _pooled: true,
      });
    }
  }

  acquire(sessionId: string, seq: number, kind: string, traceId = ""): PoolableMessage {
    const msg = this.pool.pop();
    if (msg) {
      this.reused++;
    } else {
      // Pool exhausted — allocate fresh (GC will eventually recycle).
      this.allocated++;
      const fresh: PoolableMessage = {
        v: PROTOCOL_VERSION, session_id: "", seq: 0, ts: 0,
        trace_id: "", kind: "", payload: {}, _pooled: true,
      };
      Object.assign(fresh, {});
      this.fill(fresh, sessionId, seq, kind, traceId);
      return fresh;
    }
    this.fill(msg, sessionId, seq, kind, traceId);
    return msg;
  }

  release(msg: PoolableMessage): void {
    if (this.pool.length < this.size) {
      msg.payload = {};
      this.pool.push(msg);
    }
  }

  stats(): { pooled: number; allocated: number; reused: number } {
    return { pooled: this.pool.length, allocated: this.allocated, reused: this.reused };
  }

  private fill(
    msg: PoolableMessage,
    sessionId: string, seq: number, kind: string, traceId: string,
  ): void {
    msg.v = PROTOCOL_VERSION;
    msg.session_id = sessionId;
    msg.seq = seq;
    msg.ts = Date.now() / 1000;
    msg.trace_id = traceId;
    msg.kind = kind;
  }
}
