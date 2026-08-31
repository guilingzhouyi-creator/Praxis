/**
 * Protocol v1 client bridge for the TS engine.
 *
 * Single channel between TS shell and Python3 L3 host. Enhanced:
 * AsyncGenerator streaming, batch dispatch, timing telemetry, and
 * domain-grouped helpers covering all major Python3 bridge functions.
 *
 * Python3 counterpart:
 * systems/python-reference-runtime/l2/protocol/host.py ProtocolHost — never
 * re-implement session/outbox authority here.
 */

import {
  decodeMessage, encodeMessage, makeMessage,
  type Message, type MessageKind,
} from "../protocol/wire-envelope.ts";
import { MAX_SAFE_SEQUENCE } from "../protocol/wire-types.ts";
import type { JsonObject, JsonValue } from "../protocol/wire-records.ts";

export type Transport = (line: string) => Promise<string[]>;

/** One completed round trip, reported via `BridgeOptions.onTelemetry`. */
export interface BridgeTelemetry {
  /** Message kind plus command/control op label, e.g. "command:status". */
  label: string;
  elapsedMs: number;
  responseCount: number;
}

export interface BridgeOptions {
  sessionId: string;
  transport: Transport;
  /** Optional seq wrap-around (e.g. 1<<30); unset = the safe wire bound. */
  maxSeq?: number;
  /**
   * Optional round-trip telemetry sink. Invoked after every transport
   * round trip with the elapsed time and response count.
   */
  onTelemetry?: (event: BridgeTelemetry) => void;
}

/** Highest exact sequence value representable by the TS wire encoder. */
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
    if (
      opts.maxSeq !== undefined
      && (!Number.isSafeInteger(opts.maxSeq) || opts.maxSeq < 1)
    ) {
      throw new Error(`maxSeq must be a positive safe integer <= ${MAX_SAFE_SEQUENCE}`);
    }
  }

  get sessionId(): string { return this.opts.sessionId; }

  /** Send a command envelope; returns the host's result envelopes. */
  async command(name: string, args: readonly string[] = []): Promise<Message[]> {
    const message = makeMessage(this.opts.sessionId, this.nextSeq(), "command", { name, args: [...args] });
    return (await this.roundTrip(message)).messages;
  }

  /**
   * Send a command with structured, non-authority payload fields.
   *
   * This is the typed seam for Rust-owned requests that need gate inputs
   * such as `ring`/`danger` alongside string command arguments. Host-derived
   * approval fields are still rejected by the shared envelope validator.
   */
  async commandPayload(
    name: string,
    payload: JsonObject = {},
    sessionId = this.opts.sessionId,
    traceId = "",
  ): Promise<Message[]> {
    const message = makeMessage(
      sessionId,
      this.nextSeq(),
      "command",
      { ...payload, name },
      traceId,
    );
    return (await this.roundTrip(message)).messages;
  }

  /** Attach a frontend view (`view_id` defaults to session on host). */
  async attach(sessionId: string, viewId?: string): Promise<Message[]> {
    const payload: Record<string, string> = { op: "attach", session_id: sessionId };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload, sessionId);
  }

  /** Acknowledge outbound messages up to `ackSeq` for one view/session. */
  async ack(ackSeq: number, viewId?: string, sessionId = this.opts.sessionId): Promise<Message[]> {
    const payload: Record<string, number | string> = { ack_seq: ackSeq };
    if (viewId) payload.view_id = viewId;
    return this.send("ack", payload, sessionId);
  }

  /** Request replay from `lastAcked` for one view (recovery). */
  async replay(sessionId: string, viewId?: string, lastAcked = -1): Promise<Message[]> {
    const payload: Record<string, string | number> = { op: "recovery", session_id: sessionId, last_acked: lastAcked };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload, sessionId);
  }

  // ── Streaming pipeline ──
  /** Stream one envelope and yield decoded response messages. */
  async *stream(kind: MessageKind, payload: Record<string, JsonValue>): AsyncGenerator<Message> {
    const message = makeMessage(this.opts.sessionId, this.nextSeq(), kind, payload);
    const line = encodeMessage(message);
    const responses = await this.opts.transport(line);
    for (const raw of responses) {
      yield this.decodeResponse(raw);
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

  // ── Session/control domain (host owns outbox + cursors; client mirrors) ──
  /** Detach one view from a session (host keeps the session state). */
  async detach(sessionId: string, viewId?: string): Promise<Message[]> {
    const payload: Record<string, string> = { op: "detach", session_id: sessionId };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload, sessionId);
  }

  /** Resume/recover a session outbox from `lastAcked` (host replays unacked). */
  async resume(sessionId: string, viewId?: string, lastAcked = -1): Promise<Message[]> {
    const payload: Record<string, string | number> = { op: "resume", session_id: sessionId, last_acked: lastAcked };
    if (viewId) payload.view_id = viewId;
    return this.send("control", payload, sessionId);
  }

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
    const cur = this.seq;
    const maxSeq = this.opts.maxSeq ?? MAX_SAFE_SEQUENCE;
    if (cur >= maxSeq) this.seq = 1;
    else this.seq += 1;
    return cur;
  }

  private send(
    kind: MessageKind,
    payload: Record<string, JsonValue>,
    sessionId = this.opts.sessionId,
  ): Promise<Message[]> {
    const message = makeMessage(sessionId, this.nextSeq(), kind, payload);
    return this.roundTrip(message).then((r) => r.messages);
  }

  private telemetryLabel(message: Message): string {
    const op = typeof message.payload.op === "string" ? message.payload.op : "";
    const name = typeof message.payload.name === "string" ? message.payload.name : "";
    return [message.kind, name || op].filter(Boolean).join(":");
  }

  /**
   * Decode one transport response line. Undecodable frames are a hard
   * error (ruling R7's client twin): silently dropping them turns host
   * bugs into mysterious empty results.
   */
  private decodeResponse(raw: string, expectedSessions: readonly string[] = [this.opts.sessionId]): Message {
    const decoded = decodeMessage(raw);
    if (!decoded.message) {
      throw new Error(`bridge: undecodable response: ${decoded.error}: ${raw.slice(0, 200)}`);
    }
    if (!expectedSessions.includes(decoded.message.session_id)) {
      throw new Error(
        `bridge: response session_id mismatch: expected ${expectedSessions.join(" or ")},`
          + ` got ${decoded.message.session_id}`,
      );
    }
    return decoded.message;
  }

  private async roundTrip(message: Message): Promise<RoundTripResult> {
    const start = performance.now();
    const line = encodeMessage(message);
    const responses = await this.opts.transport(line);
    const elapsedMs = performance.now() - start;
    const expectedSessions = [message.session_id];
    if (message.kind === "control" && typeof message.payload.session_id === "string") {
      expectedSessions.push(message.payload.session_id);
    }
    const messages = responses.map((raw) => this.decodeResponse(raw, expectedSessions));
    this.opts.onTelemetry?.({
      label: this.telemetryLabel(message),
      elapsedMs,
      responseCount: messages.length,
    });
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
    if (decoded.message) {
      yield decoded.message;
    }
  }
}
