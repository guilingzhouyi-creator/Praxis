/**
 * Protocol v1 client bridge for the TS engine.
 *
 * The single channel between the TS shell and the Python L3 host: every
 * envelope is built with the shared protocol mirror (envelope.ts), encoded
 * to one JSONL line, and sent over an injected transport. The TS side never
 * owns runtime state — the host's ProtocolHost keeps the outbox and ack
 * cursors, so this client only emits and decodes messages.
 */

import { decodeMessage, encodeMessage, makeMessage, type Message } from "../envelope.ts";

/** Line transport: send one encoded JSONL line, return the response lines. */
export type Transport = (line: string) => string[];

export interface BridgeOptions {
  sessionId: string;
  transport: Transport;
}

export class ProtocolBridge {
  private seq = 1;

  constructor(private readonly opts: BridgeOptions) {}

  /** Send one command envelope; returns the host's response envelopes. */
  command(name: string, args: string[] = []): Message[] {
    const message = makeMessage(this.opts.sessionId, this.seq++, "command", { name, args });
    return this.roundTrip(message);
  }

  /** Attach a frontend view (view_id optional, defaults to session id). */
  attach(sessionId: string, viewId?: string): Message[] {
    const payload: Record<string, string> = { op: "attach", session_id: sessionId };
    if (viewId) payload.view_id = viewId;
    const message = makeMessage(this.opts.sessionId, this.seq++, "control", payload);
    return this.roundTrip(message);
  }

  /** Acknowledge receipt of outbound messages up to ackSeq for one view. */
  ack(ackSeq: number, viewId?: string): Message[] {
    const payload: Record<string, number | string> = { ack_seq: ackSeq };
    if (viewId) payload.view_id = viewId;
    const message = makeMessage(this.opts.sessionId, this.seq++, "ack", payload);
    return this.roundTrip(message);
  }

  /** Request a replay from lastAcked for one view (recovery semantics). */
  replay(sessionId: string, viewId?: string, lastAcked = -1): Message[] {
    const payload: Record<string, string | number> = {
      op: "recovery",
      session_id: sessionId,
      last_acked: lastAcked,
    };
    if (viewId) payload.view_id = viewId;
    const message = makeMessage(this.opts.sessionId, this.seq++, "control", payload);
    return this.roundTrip(message);
  }

  /** Encode, send, and decode every response line. */
  private roundTrip(message: Message): Message[] {
    const line = encodeMessage(message);
    return this.opts
      .transport(line)
      .map((response) => decodeMessage(response).message)
      .filter((decoded): decoded is Message => decoded !== null);
  }
}
