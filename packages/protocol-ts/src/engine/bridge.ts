/**
 * Protocol v1 client bridge for the TS engine.
 *
 * Single channel between TS shell and Python3 L3 host. Enhanced:
 * AsyncGenerator streaming, batch dispatch, timing telemetry, and
 * domain-grouped helpers covering all major Python3 bridge functions.
 *
 * Python3 counterpart: src/l2/protocol/host.py ProtocolHost — never
 * re-implement session/outbox authority here.
 */

import {
  decodeMessage, encodeMessage, makeMessage,
  type Message, type MessageKind,
} from "../envelope.ts";
import type { JsonValue } from "../records.ts";

export type Transport = (line: string) => Promise<string[]>;

export interface BridgeOptions {
  sessionId: string;
  transport: Transport;
  /** Optional seq wrap-around (e.g. 1<<30); unset = monotonic. */
  maxSeq?: number;
}

export interface RoundTripResult {
  messages: Message[];
  elapsedMs: number;
}

/**
 * Single-channel bridge to the Python3 `ProtocolHost`.
 *
 * Owns the client `seq` and encodes/decodes every line; transport and
 * host own session/outbox authority. Domain helpers are thin 1:1 shims
 * over `command()`.
 */
export class ProtocolBridge {
  private seq = 1;

  constructor(private readonly opts: BridgeOptions) {
    if (opts.maxSeq !== undefined && (!Number.isInteger(opts.maxSeq) || opts.maxSeq < 1)) {
      throw new Error("maxSeq must be a positive integer");
    }
  }

  get sessionId(): string { return this.opts.sessionId; }

  /** Send a command envelope; returns the host's result envelopes. */
  async command(name: string, args: readonly string[] = []): Promise<Message[]> {
    const message = makeMessage(this.opts.sessionId, this.nextSeq(), "command", { name, args: [...args] });
    return (await this.roundTrip(message)).messages;
  }

  /** Attach a frontend view (`view_id` defaults to session on host). */
  async attach(sessionId: string, viewId?: string): Promise<Message[]> {
    const payload: Record<string, string> = { op: "attach", session_id: sessionId };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload);
  }

  /** Acknowledge outbound messages up to `ackSeq` for one view. */
  async ack(ackSeq: number, viewId?: string): Promise<Message[]> {
    const payload: Record<string, number | string> = { ack_seq: ackSeq };
    if (viewId) payload.view_id = viewId;
    return this.send("ack", payload);
  }

  /** Request replay from `lastAcked` for one view (recovery). */
  async replay(sessionId: string, viewId?: string, lastAcked = -1): Promise<Message[]> {
    const payload: Record<string, string | number> = { op: "recovery", session_id: sessionId, last_acked: lastAcked };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload);
  }

  // ── Streaming pipeline ──
  /** Stream one envelope and yield decoded response messages. */
  async *stream(kind: MessageKind, payload: Record<string, JsonValue>): AsyncGenerator<Message> {
    const message = makeMessage(this.opts.sessionId, this.nextSeq(), kind, payload);
    const line = encodeMessage(message);
    const responses = await this.opts.transport(line);
    for (const raw of responses) {
      const decoded = decodeMessage(raw);
      if (decoded.message) yield decoded.message;
    }
  }

  /** Send multiple commands sequentially (preserves order). */
  async batch(commands: ReadonlyArray<{ name: string; args?: readonly string[] }>): Promise<Message[][]> {
    const results: Message[][] = [];
    for (const cmd of commands) results.push(await this.command(cmd.name, cmd.args));
    return results;
  }

  // ── Settings domain ──
  async settingsGet(key = ""): Promise<Message[]> { return this.command("settings_get", key ? [key] : []); }
  async settingsSet(key: string, value: unknown): Promise<Message[]> { return this.command("settings_set", [key, JSON.stringify(value)]); }

  // ── Memory domain ──
  async memoryDigest(): Promise<Message[]> { return this.command("memory_digest", []); }
  async memoryRecall(query: string, limit = 10): Promise<Message[]> { return this.command("memory_recall", [query, String(limit)]); }
  async memoryRemember(entryType: string, content: string, ring = 2): Promise<Message[]> { return this.command("memory_remember", [entryType, content, String(ring)]); }

  // ── System domain ──
  async systemStatus(): Promise<Message[]> { return this.command("status", []); }
  async healthCheck(): Promise<Message[]> { return this.command("health", []); }

  // ── Model domain ──
  async modelSpecs(): Promise<Message[]> { return this.command("model_specs", []); }
  async modelSwitch(provider: string, model: string): Promise<Message[]> { return this.command("model_switch", [provider, model]); }

  // ── Selector domain ──
  async cellLiveness(): Promise<Message[]> { return this.command("cell_liveness", []); }

  // ── Card domain ──
  async cardSubmit(cardYaml: string): Promise<Message[]> { return this.command("card_submit", [cardYaml]); }
  async cardApprove(cardId: string): Promise<Message[]> { return this.command("card_approve", [cardId]); }

  // ── L3A domain ──
  async l3aSend(text: string, sessionId?: string): Promise<Message[]> {
    return this.command("l3a_send", sessionId ? [text, sessionId] : [text]);
  }

  // ── Tool domain ──
  async toolInvoke(toolName: string, paramsJson: string): Promise<Message[]> { return this.command("tool_invoke", [toolName, paramsJson]); }

  // ── Internal ──

  private nextSeq(): number {
    const cur = this.seq++;
    if (this.opts.maxSeq !== undefined && this.seq > this.opts.maxSeq) this.seq = 1;
    return cur;
  }

  private send(kind: MessageKind, payload: Record<string, JsonValue>): Promise<Message[]> {
    const message = makeMessage(this.opts.sessionId, this.nextSeq(), kind, payload);
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

/** Standalone helper — decode already-transported lines (shared with `ProtocolBridge.stream`). */
export async function* streamResponses(
  transport: Transport,
  line: string,
): AsyncGenerator<Message> {
  const responses = await transport(line);
  for (const raw of responses) {
    const decoded = decodeMessage(raw);
    if (decoded.message) yield decoded.message;
  }
}
