/**
 * stdio transport — JSONL request/response over a child process host.
 *
 * Writes one encoded envelope line and reads response lines until the host
 * answers with an ack envelope (the per-input response boundary the Python
 * ProtocolHost emits), with a line/time budget so a stalled host fails fast.
 */

import * as readline from "node:readline";
import type { Transport } from "../bridge.ts";

export interface StdioTransportOptions {
  input: NodeJS.ReadableStream;
  output: NodeJS.WritableStream;
  /** Maximum response lines per request (safety cap, default 256). */
  maxLines?: number;
  /** Idle timeout between response lines in ms (default 5000). */
  timeoutMs?: number;
}

/** Returns true when a response line is the ack that closes the request. */
function isAckLine(line: string): boolean {
  try {
    return JSON.parse(line).kind === "ack";
  } catch {
    return false;
  }
}

export function createStdioTransport(options: StdioTransportOptions): Transport {
  const { input, output, maxLines = 256, timeoutMs = 5000 } = options;
  const rl = readline.createInterface({ input, crlfDelay: Infinity });

  /** One pending request: resolve with collected lines once acked. */
  let pending:
    | { resolve: (lines: string[]) => void; lines: string[]; seenAck: boolean }
    | undefined;

  rl.on("line", (line) => {
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
        reject(new Error("stdio transport: concurrent request while one is pending"));
        return;
      }
      pending = { resolve, lines: [], seenAck: false };
      const timer = setTimeout(() => {
        const request = pending;
        pending = undefined;
        if (request) request.resolve(request.lines);
      }, timeoutMs);
      pending.resolve = (lines: string[]) => {
        clearTimeout(timer);
        resolve(lines);
      };
      output.write(`${line}\n`);
    });
}
