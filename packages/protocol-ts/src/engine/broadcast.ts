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
  /** Origin tab — filled automatically, used to suppress self-echo. */
  source?: string;
}

type Listener = (event: TabEvent) => void;

/**
 * Cross-tab session coordinator via `BroadcastChannel`.
 *
 * One `TabCoordinator` per tab (`tabId` must be unique per browsing
 * context); `source` tagging prevents handling our own broadcast.
 */
export class TabCoordinator {
  private channel: BroadcastChannel | undefined;
  private listeners = new Set<Listener>();

  constructor(private readonly tabId: string) {
    if (typeof tabId !== "string" || tabId.length === 0) throw new Error("tabId must be a non-empty string");
    try {
      this.channel = new BroadcastChannel("praxis-l2-sessions");
      this.channel.onmessage = (event) => {
        const data = event.data as TabEvent;
        if (!data || typeof data.type !== "string") return;
        if (data.source === this.tabId) return;
        for (const listener of this.listeners) listener(data);
      };
    } catch {
      // BroadcastChannel not supported (SSR / old browser) — degrade silently.
    }
  }

  /** Subscribe to cross-tab events; returns an unsubscribe function. */
  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Broadcast a session event to all other tabs (source is injected). */
  broadcast(event: Omit<TabEvent, "source">): void {
    this.channel?.postMessage({ ...event, source: this.tabId });
  }

  /** Close the channel and clear listeners. */
  destroy(): void {
    this.channel?.close();
    this.listeners.clear();
  }
}
