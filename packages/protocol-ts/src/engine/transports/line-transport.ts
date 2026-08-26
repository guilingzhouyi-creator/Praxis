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
import { MAX_FRAME_BYTES } from "../../types.ts";

const UTF8_ENCODER = new TextEncoder();

export interface LineTransportOptions {
  /** Register the handler that receives every inbound line. */
  onLine: (handler: (line: string) => void) => void;
  /** Write one outbound line (newline appended by the caller's sink). */
  writeLine: (line: string) => void;
  /** Maximum response lines per request (safety cap, default 256). */
  maxLines?: number;
  /** Idle timeout between response lines in ms (default 5000). */
  timeoutMs?: number;
  /** Maximum UTF-8 bytes accepted for one wire frame (default 1 MiB). */
  maxFrameBytes?: number;
}

/**
 * Returns true when a response line is the ack that closes the request.
 *
 * Hot path: every inbound response line is tested here, and the line is
 * decoded again by the bridge afterwards. A full JSON.parse per line is
 * therefore pure overhead for the (common) non-ack case — we first do a
 * cheap substring check (the serialized top-level kind field always
 * contains `"kind":"ack"` when present), and only parse to confirm when
 * the fast path matches.
 */
export function isAckLine(line: string): boolean {
  // Fast path: most lines are results/events — reject without allocating.
  if (!line.includes('"kind":"ack"')) return false;
  // Slow path: substring found — confirm with a real parse (could be a
  // payload value that happens to contain the same text).
  try {
    return JSON.parse(line).kind === "ack";
  } catch {
    return false;
  }
}

export function createLineRequestTransport(options: LineTransportOptions): Transport {
  const {
    onLine,
    writeLine,
    maxLines = 256,
    timeoutMs = 5000,
    maxFrameBytes = MAX_FRAME_BYTES,
  } = options;

  if (!Number.isInteger(maxFrameBytes) || maxFrameBytes < 1) {
    throw new Error(`maxFrameBytes must be a positive integer, got ${String(maxFrameBytes)}`);
  }

  const frameSize = (line: string): number => UTF8_ENCODER.encode(line).byteLength;

  /** One pending request: resolve with collected lines once acked. */
  let pending: {
    resolve: (lines: string[]) => void;
    reject: (error: Error) => void;
    lines: string[];
    timer: ReturnType<typeof setTimeout>;
  } | undefined;

  onLine((line: string) => {
    if (!pending) return;
    if (frameSize(line) > maxFrameBytes) {
      const request = pending;
      pending = undefined;
      clearTimeout(request.timer);
      request.reject(new Error(`line transport: response frame exceeds ${maxFrameBytes} bytes`));
      return;
    }
    pending.lines.push(line);
    if (isAckLine(line) || pending.lines.length >= maxLines) {
      const request = pending;
      pending = undefined;
      clearTimeout(request.timer);
      request.resolve(request.lines);
    }
  });

  return (line: string) =>
    new Promise<string[]>((resolve, reject) => {
      if (pending) {
        reject(new Error("line transport: concurrent request while one is pending"));
        return;
      }
      const size = frameSize(line);
      if (size > maxFrameBytes) {
        reject(new Error(`line transport: request frame exceeds ${maxFrameBytes} bytes`));
        return;
      }
      const request = {
        resolve,
        reject,
        lines: [] as string[],
        timer: undefined as unknown as ReturnType<typeof setTimeout>,
      };
      request.timer = setTimeout(() => {
        if (pending !== request) return;
        pending = undefined;
        resolve(request.lines);
      }, timeoutMs);
      pending = request;
      try {
        writeLine(line);
      } catch (error) {
        if (pending === request) {
          pending = undefined;
          clearTimeout(request.timer);
          reject(error instanceof Error ? error : new Error(String(error)));
        }
      }
    });
}
