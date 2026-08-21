/**
 * Session view projection — one session state, per-frontend shapes.
 *
 * Mirrors the Python projection registry (src/l2/protocol/projection.py):
 * web pass-through, TUI table rows, desktop rich-text blocks, and an
 * unknown-frontend fallback to web. A SessionView binds one frontend view
 * to a session via the bridge and keeps its own ack cursor — the TS side
 * never owns the runtime outbox.
 */

import type { Message } from "../envelope.ts";
import type { ProtocolBridge } from "./bridge.ts";

export interface SessionState {
  identity: Record<string, unknown>;
  events: Message[];
}

export type Projection = (state: SessionState) => Record<string, unknown>;

function summarize(event: Message): string {
  const payload = event.payload;
  if (typeof payload === "object" && payload !== null) {
    if (typeof payload.name === "string") return payload.name;
    if (typeof payload.error === "string") return payload.error;
  }
  return event.kind;
}

export function projectWeb(state: SessionState): Record<string, unknown> {
  return { frontend: "web", session: state.identity, events: state.events };
}

export function projectTui(state: SessionState): Record<string, unknown> {
  const rows = state.events.map((event) => ({
    seq: event.seq,
    kind: event.kind,
    summary: summarize(event),
  }));
  return {
    frontend: "tui",
    headers: ["seq", "kind", "summary"],
    rows,
    session_id: state.identity.session_id ?? "",
  };
}

export function projectDesktop(state: SessionState): Record<string, unknown> {
  const blocks: Record<string, unknown>[] = [
    { type: "heading", text: `Session ${String(state.identity.session_id ?? "")}` },
    {
      type: "text",
      text: `role=${String(state.identity.role ?? "")} cell=${String(state.identity.cell_id ?? "")}`,
    },
  ];
  for (const event of state.events) {
    blocks.push({ type: "event", seq: event.seq, kind: event.kind });
  }
  return { frontend: "desktop", blocks };
}

export const PROJECTIONS: Record<string, Projection> = {
  web: projectWeb,
  tui: projectTui,
  desktop: projectDesktop,
};

/** Project one session snapshot into a frontend shape (unknown → web). */
export function project(frontend: string, state: SessionState): Record<string, unknown> {
  const fn = PROJECTIONS[frontend] ?? projectWeb;
  return fn(state);
}

/** One frontend view bound to a session: attach, replay, project. */
export class SessionView {
  public lastAcked = -1;
  private identity: Record<string, unknown> = {};

  constructor(
    public readonly viewId: string,
    private readonly bridge: ProtocolBridge,
  ) {}

  /** Attach the view and capture the host's identity snapshot. */
  async attach(sessionId: string): Promise<Record<string, unknown>> {
    const responses = await this.bridge.attach(sessionId, this.viewId);
    const attached = responses.find(
      (message) => message.kind === "event" && message.payload.name === "session.attached",
    );
    this.identity = (attached?.payload.data as Record<string, unknown>) ?? {};
    return this.identity;
  }

  /** Pull the unacked replay window for this view's cursor. */
  async replay(sessionId: string, lastAcked = -1): Promise<Message[]> {
    this.lastAcked = lastAcked;
    return this.bridge.replay(sessionId, this.viewId, lastAcked);
  }

  /** Compose the projection input (identity + unacked events). */
  async state(sessionId: string): Promise<SessionState> {
    return { identity: this.identity, events: await this.replay(sessionId, this.lastAcked) };
  }
}
