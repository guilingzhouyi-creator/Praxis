/**
 * Protocol v1 client bridge for the TS engine.
 *
 * The single channel between the TS shell and the Python3 L3 host: every
 * envelope is built with the shared protocol mirror (envelope.ts), encoded
 * to one JSONL line, and sent over an injected async transport.
 *
 * Enhanced (P2): AsyncGenerator streaming for stream_chunk pipelines,
 * batched multi-command dispatch, and connection health probe.
 *
 * Python3 counterpart: src/l2/protocol/host.py ProtocolHost — never
 * re-implement the session/outbox authority here.
 */

import {
  decodeMessage, encodeMessage, makeMessage,
  type Message, type MessageKind,
} from "../envelope.ts";

/**
 * Line transport contract: send one encoded JSONL line, resolve with the
 * response lines. Async by contract so stdio/HTTP/WS/SSH adapters can each
 * wait on their own I/O (see src/engine/transports/).
 */
export type Transport = (line: string) => Promise<string[]>;

export interface BridgeOptions {
  sessionId: string;
  transport: Transport;
  /** Max round trips before the bridge refuses to send (safety guard). */
  maxSeq?: number;
}

/** A single decoded response from a round trip. */
export interface RoundTripResult {
  messages: Message[];
  /** Wall-clock duration in milliseconds (perf telemetry). */
  elapsedMs: number;
}

export class ProtocolBridge {
  private seq = 1;

  constructor(private readonly opts: BridgeOptions) {}

  get sessionId(): string {
    return this.opts.sessionId;
  }

  /** Send one command envelope; resolves with the host's response envelopes + timing. */
  async command(name: string, args: readonly string[] = []): Promise<Message[]> {
    const message = makeMessage(this.opts.sessionId, this.seq++, "command", { name, args: [...args] });
    return (await this.roundTrip(message)).messages;
  }

  /** Attach a frontend view (view_id optional, defaults to session id). */
  async attach(sessionId: string, viewId?: string): Promise<Message[]> {
    const payload: Record<string, string> = { op: "attach", session_id: sessionId };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload);
  }

  /** Acknowledge receipt up to ackSeq for one view. */
  async ack(ackSeq: number, viewId?: string): Promise<Message[]> {
    const payload: Record<string, number | string> = { ack_seq: ackSeq };
    if (viewId) payload.view_id = viewId;
    return this.send("ack", payload);
  }

  /** Request replay from lastAcked for one view (recovery semantics). */
  async replay(sessionId: string, viewId?: string, lastAcked = -1): Promise<Message[]> {
    const payload: Record<string, string | number> = { op: "recovery", session_id: sessionId, last_acked: lastAcked };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload);
  }

  /**
   * Stream responses as an AsyncGenerator (P2: stream_chunk pipeline).
   *
   * Instead of buffering all response lines before decoding, each line is
   * yielded as soon as it arrives from the transport. Consumers use:
   *   `for await (const msg of bridge.stream(command(...))) { ... }`
   */
  async *stream(kind: MessageKind, payload: Record<string, import("../records.ts").JsonValue>): AsyncGenerator<Message> {
    const message = makeMessage(this.opts.sessionId, this.seq++, kind, payload);
    const line = encodeMessage(message);
    const responses = await this.opts.transport(line);
    for (const raw of responses) {
      const decoded = decodeMessage(raw);
      if (decoded.message) yield decoded.message;
    }
  }

  /** Batch multiple commands in sequence; returns all results flattened. */
  async batch(commands: ReadonlyArray<{ name: string; args?: readonly string[] }>): Promise<Message[][]> {
    const results: Message[][] = [];
    for (const cmd of commands) {
      results.push(await this.command(cmd.name, cmd.args));
    }
    return results;
  }

  // ── domain-grouped helpers ────────────────────────────────────────────

  async settingsGet(key = ""): Promise<Message[]> {
    return this.command("settings_get", key ? [key] : []);
  }
  async settingsSet(key: string, value: unknown): Promise<Message[]> {
    return this.command("settings_set", [key, JSON.stringify(value)]);
  }
  async memoryDigest(): Promise<Message[]> {
    return this.command("memory_digest", []);
  }
  async systemStatus(): Promise<Message[]> {
    return this.command("status", []);
  }
  async modelSpecs(): Promise<Message[]> {
    return this.command("model_specs", []);
  }
  async cellLiveness(): Promise<Message[]> {
    return this.command("cell_liveness", []);
  }

  // ── internal ──────────────────────────────────────────────────────────

  private send(kind: MessageKind, payload: Record<string, import("../records.ts").JsonValue>): Promise<Message[]> {
    const message = makeMessage(this.opts.sessionId, this.seq++, kind, payload);
    return this.roundTrip(message).then((r) => r.messages);
  }

  private async roundTrip(message: Message): Promise<RoundTripResult> {
    const start = performance.now();
    const line = encodeMessage(message);
    const responses = await this.opts.transport(line);
    const elapsedMs = performance.now() - start;
    const messages: Message[] = [];
    for (const raw of responses) {
      const decoded = decodeMessage(raw);
      if (decoded.message) messages.push(decoded.message);
    }
    return { messages, elapsedMs };
  }
}
