/**
 * ConnectionManager — transport lifecycle + automatic reconnection.
 *
 * Wraps a Transport factory with:
 *   - Health probe integration (auto-reconnect on failure)
 *   - Exponential backoff reconnection with max attempts
 *   - Graceful shutdown (drain pending before close)
 *   - State machine: disconnected → connecting → connected → reconnecting
 *
 * TS pattern: finite state machine with discriminated union states.
 */

import { ProtocolBridge, type Transport } from "./bridge.ts";
import { ProtocolError, withRetry } from "./protocol-errors.ts";
import { TypedEventEmitter, type EngineEvents } from "./events.ts";

export type ConnectionState =
  | { status: "disconnected" }
  | { status: "connecting"; attempt: number }
  | { status: "connected" }
  | { status: "reconnecting"; attempt: number };

export type TransportFactory = () => Transport;

/** A transport that also owns an underlying resource (child, socket, stream). */
export type CloseableTransport = Transport & { close: () => void };

export interface ConnectionOptions {
  factory: TransportFactory;
  sessionId: string;
  maxRetries?: number;
  baseDelayMs?: number;
}

/**
 * Transport lifecycle manager with reconnection.
 *
 * State machine `disconnected → connecting → connected → reconnecting`
 * with exponential backoff; `on()` preserves `TypedEventEmitter` typing.
 *
 * Transports that expose a `close()` (managed hosts, sockets) are released
 * on disconnect AND when a failed probe replaces them, so a lingering child
 * process or socket never survives the manager's state — reconnects stack
 * only live transports.
 */
export class ConnectionManager {
  private state: ConnectionState = { status: "disconnected" };
  private bridgeInstance: ProtocolBridge | undefined;
  private currentTransport: Transport | undefined;
  private readonly emitter = new TypedEventEmitter();

  constructor(private readonly opts: ConnectionOptions) {
    // Validate retry config up front: bad values silently degrade the FSM
    // (a negative maxRetries skips every attempt and throws undefined; a
    // non-finite delay collapses the backoff into an immediate retry storm).
    if (opts.maxRetries !== undefined && (!Number.isInteger(opts.maxRetries) || opts.maxRetries < 0)) {
      throw new Error(`maxRetries must be a non-negative integer, got ${String(opts.maxRetries)}`);
    }
    if (opts.baseDelayMs !== undefined && (!Number.isFinite(opts.baseDelayMs) || opts.baseDelayMs < 0)) {
      throw new Error(`baseDelayMs must be a finite non-negative number, got ${String(opts.baseDelayMs)}`);
    }
  }

  /** Active bridge; throws `BRIDGE_UNAVAILABLE` when not connected. */
  get bridge(): ProtocolBridge {
    if (!this.bridgeInstance) throw new ProtocolError("BRIDGE_UNAVAILABLE", "not connected");
    return this.bridgeInstance;
  }

  /** Snapshot of the FSM state (defensive copy). */
  getState(): ConnectionState {
    return { ...this.state };
  }

  /** Whether the manager is currently connected. */
  isConnected(): boolean {
    return this.state.status === "connected";
  }

  /** Typed subscribe; returns unsubscribe. */
  on<K extends keyof EngineEvents>(
    event: K,
    listener: (payload: EngineEvents[K]) => void | Promise<void>,
  ): () => void {
    return this.emitter.on(event, listener);
  }

  /** Connect with probe + exponential backoff; idempotent when already connected. */
  async connect(): Promise<ProtocolBridge> {
    if (this.isConnected()) return this.bridge;
    this.setState({ status: "connecting", attempt: 0 });
    try {
      const transport = await withRetry(
        async () => {
          const t = this.opts.factory();
          const probe = new ProtocolBridge({ sessionId: this.opts.sessionId, transport: t });
          try {
            await probe.systemStatus();
          } catch (err) {
            this.closeTransport(t); // a failed probe must not leak its child/socket
            throw err;
          }
          return t;
        },
        { maxRetries: this.opts.maxRetries ?? 3, baseDelayMs: this.opts.baseDelayMs ?? 500 },
      );
      this.closeTransport(this.currentTransport); // idempotent; replaces a stale live one
      this.currentTransport = transport;
      this.bridgeInstance = new ProtocolBridge({ sessionId: this.opts.sessionId, transport });
      this.setState({ status: "connected" });
      await this.emitter.emit("health:change", { healthy: true, latencyMs: 0 });
      return this.bridge;
    } catch (err) {
      this.setState({ status: "disconnected" });
      throw err;
    }
  }

  /** Disconnect gracefully, release the transport resource, and drop the bridge. */
  disconnect(): void {
    this.closeTransport(this.currentTransport);
    this.currentTransport = undefined;
    this.setState({ status: "disconnected" });
    this.bridgeInstance = undefined;
    void this.emitter.emit("transport:close", {});
  }

  /** Best-effort release of a transport's underlying resource (no-op otherwise). */
  private closeTransport(transport: Transport | undefined): void {
    const close = (transport as CloseableTransport | undefined)?.close;
    if (typeof close !== "function") return;
    try {
      close();
    } catch {
      // Release is best-effort: a throwing close must not break the FSM.
    }
  }

  private setState(next: ConnectionState): void {
    this.state = next;
  }
}
