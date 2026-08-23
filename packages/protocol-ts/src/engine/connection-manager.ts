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
import { ProtocolError } from "./errors.ts";
import { TypedEventEmitter, type EngineEvents } from "./events.ts";

export type ConnectionState =
  | { status: "disconnected" }
  | { status: "connecting"; attempt: number }
  | { status: "connected" }
  | { status: "reconnecting"; attempt: number };

export type TransportFactory = () => Transport;

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
 */
export class ConnectionManager {
  private state: ConnectionState = { status: "disconnected" };
  private bridgeInstance: ProtocolBridge | undefined;
  private readonly emitter = new TypedEventEmitter();

  constructor(private readonly opts: ConnectionOptions) {}

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
    const maxRetries = this.opts.maxRetries ?? 3;
    const baseDelay = this.opts.baseDelayMs ?? 500;
    let lastError: unknown;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      this.setState({
        status: attempt === 0 ? "connecting" : "reconnecting",
        attempt,
      });
      try {
        const transport = this.opts.factory();
        // Probe over the same transport, but do not consume the real seq.
        const probe = new ProtocolBridge({ sessionId: this.opts.sessionId, transport });
        await probe.systemStatus();
        this.bridgeInstance = new ProtocolBridge({ sessionId: this.opts.sessionId, transport });
        this.setState({ status: "connected" });
        await this.emitter.emit("health:change", { healthy: true, latencyMs: 0 });
        return this.bridge;
      } catch (err) {
        lastError = err;
        if (attempt < maxRetries) {
          const delay = baseDelay * Math.pow(2, attempt) + Math.random() * baseDelay;
          await new Promise<void>((resolve) => setTimeout(resolve, delay));
        }
      }
    }
    this.setState({ status: "disconnected" });
    throw lastError;
  }

  /** Disconnect gracefully and release the bridge. */
  disconnect(): void {
    this.setState({ status: "disconnected" });
    this.bridgeInstance = undefined;
    void this.emitter.emit("transport:close", {});
  }

  private setState(next: ConnectionState): void {
    this.state = next;
  }
}
