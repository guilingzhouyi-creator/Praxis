/**
 * TypedEventEmitter — compile-time safe pub/sub for engine lifecycle events.
 *
 * TS pattern: mapped type constrains event names to their payload types,
 * so `emit("unknown", data)` is a compile error. `on()` returns an
 * unsubscribe function. Internally uses `any` for heterogeneous storage;
 * the public API remains fully typed.
 */

export interface EngineEvents {
  "session:attach": { sessionId: string; viewId: string };
  "session:detach": { sessionId: string; viewId: string };
  ack: { sessionId: string; ackSeq: number };
  error: { code: string; message: string };
  "health:change": { healthy: boolean; latencyMs: number };
  "transport:close": Record<string, never>;
}

type EventKey = keyof EngineEvents;
// Internal storage uses `any` — the public API provides type safety.
/* eslint-disable @typescript-eslint/no-explicit-any */
type AnyListener = (...args: any[]) => any;

export class TypedEventEmitter {
  private listeners = new Map<string, Set<AnyListener>>();

  on<K extends EventKey>(event: K, listener: (payload: EngineEvents[K]) => void | Promise<void>): () => void {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    const set = this.listeners.get(event)!;
    set.add(listener as AnyListener);
    return () => set.delete(listener as AnyListener);
  }

  once<K extends EventKey>(event: K, listener: (payload: EngineEvents[K]) => void | Promise<void>): () => void {
    const wrapped = ((payload: EngineEvents[K]) => {
      this.off(event, wrapped);
      return listener(payload);
    }) as AnyListener;
    return this.on(event, wrapped as any);
  }

  off<K extends EventKey>(event: K, listener: (payload: EngineEvents[K]) => void | Promise<void>): void {
    this.listeners.get(event)?.delete(listener as AnyListener);
  }

  async emit<K extends EventKey>(event: K, payload: EngineEvents[K]): Promise<void> {
    const set = this.listeners.get(event);
    if (!set) return;
    for (const listener of [...set]) {
      try {
        await listener(payload);
      } catch (err) {
        console.error(`[TypedEventEmitter] "${String(event)}" listener error:`, err);
      }
    }
  }

  removeAll(): void {
    this.listeners.clear();
  }
}
