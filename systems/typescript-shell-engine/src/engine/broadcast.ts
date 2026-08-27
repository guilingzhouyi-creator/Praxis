/**
 * BroadcastChannel-based multi-tab session coordination.
 *
 * When the TS engine runs in a browser context, multiple tabs may share
 * one Python3 host connection. This module broadcasts session lifecycle
 * events (attach/detach/ack) across tabs so all views stay synchronised
 * without polling. Falls back to a no-op on unsupported environments.
 *
 * TS pattern: EventTarget-based pub/sub with type-safe event payloads via
 * generics and `CustomEvent<T>` detail.
 */

export interface TabEvent {
  type: "session-attach" | "session-detach" | "ack" | "recovery";
  sessionId: string;
  viewId?: string;
  ackSeq?: number;
}

type Listener = (event: TabEvent) => void;

/** Cross-tab coordinator via `BroadcastChannel` (no-op where unsupported). */
export class TabCoordinator {
  private channel: BroadcastChannel | undefined;
  private listeners = new Set<Listener>();

  constructor(private readonly _tabId: string) {
    try {
      this.channel = new BroadcastChannel("praxis-l2-sessions");
      this.channel.onmessage = (event) => {
        const data = event.data as TabEvent;
        if (data?.type) for (const l of this.listeners) l(data);
      };
    } catch {
      // BroadcastChannel not supported — degrade silently.
    }
  }

  /** Subscribe; returns unsubscribe. */
  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Broadcast to other tabs. */
  broadcast(event: TabEvent): void {
    this.channel?.postMessage(event);
  }

  /** Close and clear. */
  destroy(): void {
    this.channel?.close();
    this.listeners.clear();
  }
}
