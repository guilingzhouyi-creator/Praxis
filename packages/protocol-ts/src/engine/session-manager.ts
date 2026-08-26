/**
 * SessionManager — multi-frontend view multiplexing over one session.
 *
 * Mirrors the Python3 ProtocolHost multiplexing semantics (one session,
 * N frontend views, each with its own ack cursor) on the TS client side.
 * The host stays the authority for the runtime outbox and cursors; this
 * manager is a local mirror that keeps the per-view replay window used by
 * projections, advances the shared watermark to the lagging view, and
 * emits ack/recovery control messages over the bridge.
 */

import type { Message } from "../envelope.ts";
import type { ProtocolBridge } from "./bridge.ts";

/** One frontend view bound to a session: its own ack cursor + replay window. */
export interface ViewState {
  viewId: string;
  lastAcked: number;
  /** Events delivered to this view but not yet acked (local replay mirror). */
  unacked: Message[];
}

/** One session's multiplexer: the shared event stream + all bound views. */
export class SessionMultiplexer {
  private views = new Map<string, ViewState>();
  private events: Message[] = [];
  private eventKeys = new Set<string>();

  constructor(public readonly sessionId: string) {}

  /** Attach a view (idempotent); returns its fresh ViewState. */
  attach(viewId: string): ViewState {
    const existing = this.views.get(viewId);
    if (existing) return existing;
    const state: ViewState = { viewId, lastAcked: -1, unacked: [] };
    this.views.set(viewId, state);
    return state;
  }

  detach(viewId: string): void {
    this.views.delete(viewId);
  }

  /** Record one outbound event in the shared stream and deliver to every view. */
  emit(message: Message): void {
    // ACKs close a transport request; they are not session events and must not
    // become replayable state in the local projection mirror.
    if (message.kind === "ack") return;
    const key = this.messageKey(message);
    if (this.eventKeys.has(key)) return;
    this.eventKeys.add(key);
    this.events.push(message);
    for (const view of this.views.values()) {
      if (!view.unacked.some((event) => this.messageKey(event) === key)) view.unacked.push(message);
    }
  }

  /**
   * Ack up to a seq for one view (non-destructive: other views keep their
   * windows) and advance the shared watermark to the lagging view.
   */
  ack(viewId: string, ackSeq: number): void {
    const view = this.views.get(viewId);
    if (!view) return;
    view.lastAcked = Math.max(view.lastAcked, ackSeq);
    view.unacked = view.unacked.filter((e) => e.seq > ackSeq);
  }

  /** Replay the unacked window for one view (recovery semantics). */
  replay(viewId: string, lastAcked = -1): Message[] {
    const view = this.views.get(viewId);
    if (!view) return [];
    view.lastAcked = lastAcked;
    view.unacked = this.events.filter((e) => e.seq > lastAcked);
    return [...view.unacked];
  }

  /** Shared watermark = the lagging view's lastAcked (lowest of all views). */
  watermark(): number {
    if (this.views.size === 0) return -1;
    let lowest = Infinity;
    for (const view of this.views.values()) lowest = Math.min(lowest, view.lastAcked);
    return lowest === Infinity ? -1 : lowest;
  }

  listViews(): string[] {
    return [...this.views.keys()];
  }

  viewState(viewId: string): ViewState | undefined {
    return this.views.get(viewId);
  }

  private messageKey(message: Message): string {
    return `${message.session_id}:${message.seq}:${message.kind}`;
  }
}

/** Multi-session container: attach/ack/replay across sessions via the bridge. */
export class SessionManager {
  private sessions = new Map<string, SessionMultiplexer>();

  constructor(private readonly bridge: ProtocolBridge) {}

  private multiplexer(sessionId: string): SessionMultiplexer {
    let mux = this.sessions.get(sessionId);
    if (!mux) {
      mux = new SessionMultiplexer(sessionId);
      this.sessions.set(sessionId, mux);
    }
    return mux;
  }

  /** Attach a view to a session: register locally + control message to host. */
  async attach(sessionId: string, viewId: string): Promise<ViewState> {
    const mux = this.multiplexer(sessionId);
    const state = mux.attach(viewId);
    const responses = await this.bridge.attach(sessionId, viewId);
    for (const response of responses) mux.emit(response);
    return state;
  }

  /** Ack one view up to a seq: local cursor + control message to host. */
  async ack(sessionId: string, viewId: string, ackSeq: number): Promise<void> {
    const mux = this.multiplexer(sessionId);
    mux.ack(viewId, ackSeq);
    await this.bridge.ack(ackSeq, viewId, sessionId);
  }

  /** Replay one view's window: local mirror + recovery control to host. */
  async replay(sessionId: string, viewId: string, lastAcked = -1): Promise<Message[]> {
    const mux = this.multiplexer(sessionId);
    const local = mux.replay(viewId, lastAcked);
    const responses = await this.bridge.replay(sessionId, viewId, lastAcked);
    for (const response of responses) mux.emit(response);
    const merged = mux.replay(viewId, lastAcked);
    return merged.length > 0 ? merged : local;
  }

  /** Shared watermark for a session (lagging view). */
  watermark(sessionId: string): number {
    return this.multiplexer(sessionId).watermark();
  }

  listSessions(): string[] {
    return [...this.sessions.keys()];
  }
}
