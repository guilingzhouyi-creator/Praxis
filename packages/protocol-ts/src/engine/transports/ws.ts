/**
 * WebSocket transport — one JSONL envelope per message.
 *
 * Python counterpart: reserved — no /api/v2/ws endpoint exists yet, so this
 * adapter follows the §2.6 line contract (same ack boundary as every
 * adapter) and a future host WS endpoint can be attached without touching
 * the bridge or the engine. Uses the Node native WebSocket; the class is
 * injectable so tests can drive a fake server.
 */

import { createLineRequestTransport, type LineTransportOptions } from "./line-transport.ts";
import type { Transport } from "../bridge.ts";

export interface WsTransportOptions {
  /** ws:// or wss:// endpoint carrying the JSONL envelope stream. */
  url: string;
  /** Maximum response lines per request (safety cap, default 256). */
  maxLines?: number;
  /** Idle timeout between response lines in ms (default 5000). */
  timeoutMs?: number;
  /** Injectable WebSocket class for tests / fake servers. */
  WebSocketImpl?: typeof WebSocket;
  /** Pre-built WebSocket instance — tests drive the exact socket. */
  WebSocketInstance?: WebSocket;
}

export function createWsTransport(options: WsTransportOptions): Transport {
  const { url, maxLines = 256, timeoutMs = 5000 } = options;
  const ws = options.WebSocketInstance ?? new (options.WebSocketImpl ?? WebSocket)(url);
  const Ws = ws.constructor as typeof WebSocket;

  const engineOptions: LineTransportOptions = {
    onLine: (handler) => {
      ws.onmessage = (event) => handler(String(event.data));
    },
    writeLine: (line) => {
      // Fail fast when the socket is not open (§2.6 robustness) — a caller
      // that awaits the open event never hits this.
      if (ws.readyState !== Ws.OPEN) {
        throw new Error(`ws transport: socket not open (readyState=${ws.readyState})`);
      }
      ws.send(line);
    },
    maxLines,
    timeoutMs,
  };
  return createLineRequestTransport(engineOptions);
}
