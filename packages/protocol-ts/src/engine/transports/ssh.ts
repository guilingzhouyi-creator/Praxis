/**
 * SSH transport — JSONL over an ssh2 exec channel to a remote stdio host.
 *
 * The remote end runs the host entry (default `python -m l2.protocol`), so
 * the channel's stdout is a line stream with the same ack boundary as the
 * stdio adapter. Requires the ssh2 dev dependency; the client factory is
 * injectable so tests can drive a fake channel.
 *
 * Readiness handshake: connect + exec are asynchronous, so writes issued
 * before the channel exists are queued and flushed once the channel is
 * attached — callers do not need to wait or sleep. A full queue fails fast
 * (safety cap) and a stalled connect is bounded by the transport timeout.
 */

// @ts-ignore — node:readline types require @types/node at build time
import * as readline from "node:readline";
// @ts-ignore — ssh2 types provided by @types/ssh2
import { Client, type ClientChannel } from "ssh2";
import { createLineRequestTransport, type LineTransportOptions } from "./line-transport.ts";
import type { Transport } from "../bridge.ts";

/** Minimal channel surface the engine needs (injectable for tests). */
export interface SshChannelLike {
  stdout: any;
  write(data: string): void;
}

export interface SshTransportOptions {
  host: string;
  port?: number;
  username: string;
  password?: string;
  privateKey?: string;
  /** Remote host entry (default `python -m l2.protocol`). */
  command?: string;
  /** Maximum response lines per request (safety cap, default 256). */
  maxLines?: number;
  /** Idle timeout between response lines in ms (default 5000). */
  timeoutMs?: number;
  /** Maximum UTF-8 bytes accepted for one wire frame (default 1 MiB). */
  maxFrameBytes?: number;
  /** Max writes buffered while the channel connects (default 64). */
  maxPendingWrites?: number;
  /** Injectable client factory for tests (default: ssh2 Client). */
  createClient?: () => Client;
}

export function createSshTransport(options: SshTransportOptions): Transport {
  const {
    host,
    port = 22,
    username,
    password,
    privateKey,
    command = "python -m l2.protocol",
    maxLines = 256,
    timeoutMs = 5000,
    maxFrameBytes,
    maxPendingWrites = 64,
  } = options;
  const createClient = options.createClient ?? (() => new Client());
  const client = createClient();

  let channel: SshChannelLike | undefined;
  let pendingHandler: ((line: string) => void) | undefined;
  const pendingWrites: string[] = [];

  const attachChannel = (stream: SshChannelLike) => {
    channel = stream;
    const rl = readline.createInterface({ input: stream.stdout, crlfDelay: Infinity });
    if (pendingHandler) rl.on("line", pendingHandler);
    // Flush the queued writes now that the channel is ready.
    while (pendingWrites.length > 0) {
      const line = pendingWrites.shift()!;
      stream.write(line);
    }
  };

  const engineOptions: LineTransportOptions = {
    onLine: (handler) => {
      pendingHandler = handler;
      if (channel) attachChannel(channel);
    },
    writeLine: (line) => {
      if (channel) {
        channel.write(`${line}\n`);
        return;
      }
      // Channel still connecting — queue the write (readiness handshake).
      if (pendingWrites.length >= maxPendingWrites) {
        throw new Error(`ssh transport: channel not ready and ${maxPendingWrites} writes queued`);
      }
      pendingWrites.push(`${line}\n`);
    },
    maxLines,
    timeoutMs,
    maxFrameBytes,
  };
  const transport = createLineRequestTransport(engineOptions);

  client.on("ready", () => {
    client.exec(command, (error: any, stream: any) => {
      if (error || !stream) return;
      attachChannel(stream as unknown as SshChannelLike);
    });
  });
  client.connect({ host, port, username, password, privateKey });

  return transport;
}
