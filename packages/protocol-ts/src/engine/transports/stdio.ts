/**
 * stdio transport — JSONL request/response over a child process host.
 *
 * Writes one encoded envelope line and reads response lines until the host
 * answers with an ack envelope (the per-input response boundary the Python3
 * ProtocolHost emits), with a line/time budget so a stalled host fails fast.
 * Host entry: `python -m l2.protocol` (see tests/e2e.stdio.test.ts).
 * Built on the shared line request/response engine (line-transport.ts).
 */

// @ts-ignore — node:readline types require @types/node at build time
import * as readline from "node:readline";
import { createLineRequestTransport, type LineTransportOptions } from "./line-transport.ts";
import type { Transport } from "../bridge.ts";

export interface StdioTransportOptions {
  input: any;
  output: any;
  /** Maximum response lines per request (safety cap, default 256). */
  maxLines?: number;
  /** Idle timeout between response lines in ms (default 5000). */
  timeoutMs?: number;
  /** Maximum UTF-8 bytes accepted for one wire frame (default 1 MiB). */
  maxFrameBytes?: number;
}

export function createStdioTransport(options: StdioTransportOptions): Transport {
  const { input, output, maxLines = 256, timeoutMs = 5000, maxFrameBytes } = options;
  const rl = readline.createInterface({ input, crlfDelay: Infinity });

  const engineOptions: LineTransportOptions = {
    onLine: (handler) => rl.on("line", handler),
    writeLine: (line) => output.write(`${line}\n`),
    maxLines,
    timeoutMs,
    maxFrameBytes,
  };
  return createLineRequestTransport(engineOptions);
}
