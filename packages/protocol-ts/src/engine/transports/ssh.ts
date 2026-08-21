/**
 * SSH transport — JSONL over an ssh2 exec channel to a remote stdio host.
 *
 * The remote end runs the host entry (default `python -m l2.protocol`), so
 * the channel's stdout is a line stream with the same ack boundary as the
 * stdio adapter. Requires the ssh2 dev dependency; the client factory is
 * injectable so tests can drive a fake channel.
 *
 * Usage note: connect + exec are asynchronous — writes before the channel
 * is ready throw (fail fast); callers should wait for the channel (see the
 * tests for the ready pattern) or extend with a readiness handshake.
 */

import * as readline from "node:readline";
import { Client, type ClientChannel } from "ssh2";
import { createLineRequestTransport, type LineTransportOptions } from "./line-transport.ts";
import type { Transport } from "../bridge.ts";

/** Minimal channel surface the engine needs (injectable for tests). */
export interface SshChannelLike {
  stdout: NodeJS.ReadableStream;
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
  } = options;
  const createClient = options.createClient ?? (() => new Client());
  const client = createClient();

  let channel: SshChannelLike | undefined;
  let pendingHandler: ((line: string) => void) | undefined;

  const attachChannel = (stream: SshChannelLike) => {
    channel = stream;
    const rl = readline.createInterface({ input: stream.stdout, crlfDelay: Infinity });
    if (pendingHandler) rl.on("line", pendingHandler);
  };

  const engineOptions: LineTransportOptions = {
    onLine: (handler) => {
      pendingHandler = handler;
      if (channel) attachChannel(channel);
    },
    writeLine: (line) => {
      if (!channel) throw new Error("ssh transport: channel not ready yet");
      channel.write(`${line}\n`);
    },
    maxLines,
    timeoutMs,
  };
  const transport = createLineRequestTransport(engineOptions);

  client.on("ready", () => {
    client.exec(command, (error, stream) => {
      if (error || !stream) return;
      attachChannel(stream as unknown as SshChannelLike);
    });
  });
  client.connect({ host, port, username, password, privateKey });

  return transport;
}
