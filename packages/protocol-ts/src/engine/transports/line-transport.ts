/**
 * Line request/response transport engine (protocol-agnostic).
 *
 * Shared by stdio/WS/SSH adapters: one request writes a single JSONL line
 * and resolves once the host answers with an ack line (the per-input
 * response boundary every ProtocolHost adapter emits), or when the line
 * budget / timeout expires. A second request while one is pending is
 * rejected — transports never interleave requests (§2.6 contract).
 *
 * An adapter only needs to provide a line source (`onLine` registration)
 * and a line sink (`writeLine`); see stdio.ts / ws.ts / ssh.ts.
 */

import type { Transport } from "../bridge.ts";

export interface LineTransportOptions {
  /** Register the handler that receives every inbound line. */
  onLine: (handler: (line: string) => void) => void;
  /** Write one outbound line (newline appended by the caller's sink). */
  writeLine: (line: string) => void;
  /** Maximum response lines per request (safety cap, default 256). */
  maxLines?: number;
  /** Idle timeout between response lines in ms (default 5000). */
  timeoutMs?: number;
}

/** Returns true when a response line is the ack that closes the request. */
export function isAckLine(line: string): boolean {
  try {
    return JSON.parse(line).kind === "ack";
  } catch {
    return false;
  }
}

export function createLineRequestTransport(options: LineTransportOptions): Transport {
  const { onLine, writeLine, maxLines = 256, timeoutMs = 5000 } = options;

  /** One pending request: resolve with collected lines once acked. */
  let pending: { resolve: (lines: string[]) => void; lines: string[] } | undefined;

  onLine((line: string) => {
    if (!pending) return;
    pending.lines.push(line);
    if (isAckLine(line) || pending.lines.length >= maxLines) {
      const request = pending;
      pending = undefined;
      request.resolve(request.lines);
    }
  });

  return (line: string) =>
    new Promise<string[]>((resolve, reject) => {
      if (pending) {
        reject(new Error("line transport: concurrent request while one is pending"));
        return;
      }
      pending = { resolve, lines: [] };
      const timer = setTimeout(() => {
        const request = pending;
        pending = undefined;
        if (request) request.resolve(request.lines);
      }, timeoutMs);
      pending.resolve = (lines: string[]) => {
        clearTimeout(timer);
        resolve(lines);
      };
      writeLine(line);
    });
}
