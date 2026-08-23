/**
 * Protocol v1 client bridge for the TS engine.
 *
 * The single channel between the TS shell and the Python3 L3 host: every
 * envelope is built with the shared protocol mirror (envelope.ts), encoded
 * to one JSONL line, and sent over an injected async transport. The TS side
 * never owns runtime state — the host's ProtocolHost keeps the outbox and
 * ack cursors, so this client only emits and decodes messages.
 *
 * Python3 counterpart: src/l2/protocol/host.py ProtocolHost — command maps
 * to handle_message, attach/ack/replay to the control ops; never re-implement
 * the session/outbox authority here.
 */

import { decodeMessage, encodeMessage, makeMessage, type Message } from "../envelope.ts";

/**
 * Line transport: send one encoded JSONL line, resolve with the response
 * lines. Async by contract so stdio/HTTP/WS/SSH adapters can each wait on
 * their own I/O (see src/engine/transports/).
 */
export type Transport = (line: string) => Promise<string[]>;

export interface BridgeOptions {
  sessionId: string;
  transport: Transport;
}

export class ProtocolBridge {
  private seq = 1;

  constructor(private readonly opts: BridgeOptions) {}

  /** Send one command envelope; resolves with the host's response envelopes. */
  async command(name: string, args: string[] = []): Promise<Message[]> {
    const message = makeMessage(this.opts.sessionId, this.seq++, "command", { name, args });
    return this.roundTrip(message);
  }

  /** Attach a frontend view (view_id optional, defaults to session id). */
  async attach(sessionId: string, viewId?: string): Promise<Message[]> {
    const payload: Record<string, string> = { op: "attach", session_id: sessionId };
    if (viewId) payload.view_id = viewId;
    const message = makeMessage(this.opts.sessionId, this.seq++, "control", payload);
    return this.roundTrip(message);
  }

  /** Acknowledge receipt of outbound messages up to ackSeq for one view. */
  async ack(ackSeq: number, viewId?: string): Promise<Message[]> {
    const payload: Record<string, number | string> = { ack_seq: ackSeq };
    if (viewId) payload.view_id = viewId;
    const message = makeMessage(this.opts.sessionId, this.seq++, "ack", payload);
    return this.roundTrip(message);
  }

  /** Request a replay from lastAcked for one view (recovery semantics). */
  async replay(sessionId: string, viewId?: string, lastAcked = -1): Promise<Message[]> {
    const payload: Record<string, string | number> = {
      op: "recovery",
      session_id: sessionId,
      last_acked: lastAcked,
    };
    if (viewId) payload.view_id = viewId;
    const message = makeMessage(this.opts.sessionId, this.seq++, "control", payload);
    return this.roundTrip(message);
  }

  // ── domain-grouped command helpers ────────────────────────────────────
  // Each maps 1:1 to a Python3 command semantic (config/commands.yaml
  // categories); the host stays the authority and answers with result
  // envelopes. The TS side never re-implements the domain logic.

  /** settings domain — read all/one setting, write one (single write authority is the host). */
  async settingsGet(key = ""): Promise<Message[]> {
    return this.command("settings_get", key ? [key] : []);
  }

  /** settings domain — write a key; value travels as its JSON representation. */
  async settingsSet(key: string, value: unknown): Promise<Message[]> {
    return this.command("settings_set", [key, JSON.stringify(value)]);
  }

  /** memory domain — digest list (L3A compression operator state). */
  async memoryDigest(): Promise<Message[]> {
    return this.command("memory_digest", []);
  }

  /** system domain — status/health summary from the host. */
  async systemStatus(): Promise<Message[]> {
    return this.command("status", []);
  }

  /** model domain — resolved model-spec snapshot (mirrors /model specs). */
  async modelSpecs(): Promise<Message[]> {
    return this.command("model_specs", []);
  }

  /** selector domain — cell/agent reachability dicts (zero object handles). */
  async cellLiveness(): Promise<Message[]> {
    return this.command("cell_liveness", []);
  }

  /** Encode, send, and decode every response line. */
  private async roundTrip(message: Message): Promise<Message[]> {
    const line = encodeMessage(message);
    const responses = await this.opts.transport(line);
    return responses
      .map((response) => decodeMessage(response).message)
      .filter((decoded): decoded is Message => decoded !== null);
  }
}
