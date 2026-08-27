import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";

import { decodeMessage, encodeMessage, makeMessage } from "../src/wire-envelope.ts";
import {
  createConfiguredHostTransport,
  createRustHostTransport,
  isRustHostEnabled,
  resolveHostImplementation,
  type ChildProcessLike,
  type HostSpawnOptions,
  type SpawnImplementation,
} from "../src/engine/transports/rust-host.ts";

class FakeChild implements ChildProcessLike {
  readonly stdout = new PassThrough();
  readonly stderr = new PassThrough();
  readonly received: string[] = [];
  suppressResponses = false;
  readonly stdin = {
    write: (data: string) => {
      this.received.push(data);
      if (this.suppressResponses) return;
      const request = decodeMessage(data.trim()).message;
      if (!request) return;
      this.stdout.write(`${encodeMessage(makeMessage(request.session_id, 1, "result", { success: true }))}\n`);
      this.stdout.write(`${encodeMessage(makeMessage(request.session_id, 2, "ack", { ack_seq: request.seq }))}\n`);
    },
    end: () => this.stdout.end(),
  };
  private readonly listeners = new Map<string, Array<(...args: unknown[]) => void>>();
  killed = false;

  on(event: string, listener: (...args: unknown[]) => void): this {
    const listeners = this.listeners.get(event) ?? [];
    listeners.push(listener);
    this.listeners.set(event, listeners);
    return this;
  }

  kill(): boolean {
    this.killed = true;
    return true;
  }

  emit(event: string, ...args: unknown[]): void {
    for (const listener of this.listeners.get(event) ?? []) listener(...args);
  }
}

function fakeFactory(log: { command?: string; args?: readonly string[]; options?: HostSpawnOptions; child?: FakeChild }): SpawnImplementation {
  return (command, args, options) => {
    log.command = command;
    log.args = args;
    log.options = options;
    log.child = new FakeChild();
    return log.child;
  };
}

describe("configured host transport", () => {
  it("keeps Rust opt-in and resolves production Python by default", () => {
    expect(isRustHostEnabled({})).toBe(false);
    expect(isRustHostEnabled({ PRAXIS_RUST_HOST: "0" })).toBe(false);
    expect(isRustHostEnabled({ PRAXIS_RUST_HOST: "true" })).toBe(true);
    expect(isRustHostEnabled({ PRAXIS_RUST_HOST: "rust" })).toBe(true);
    expect(resolveHostImplementation({})).toBe("python");
    expect(resolveHostImplementation({ PRAXIS_RUST_HOST: "on" })).toBe("rust");
  });

  it("selects the configured Rust executable and keeps stderr separate", async () => {
    const log: { command?: string; args?: readonly string[]; options?: HostSpawnOptions; child?: FakeChild } = {};
    const transport = createConfiguredHostTransport({
      env: { PRAXIS_RUST_HOST: "1", PRAXIS_RUST_HOST_BIN: "/tmp/rust-host" },
      spawnImpl: fakeFactory(log),
    });
    expect(transport.host).toBe("rust");
    expect(log.command).toBe("/tmp/rust-host");
    expect(log.args).toEqual([]);
    expect(log.options?.stdio).toEqual(["pipe", "pipe", "pipe"]);

    const lines = await transport(encodeMessage(makeMessage("s", 7, "command", { name: "status" })));
    expect(lines).toHaveLength(2);
    expect(decodeMessage(lines[0]).message?.kind).toBe("result");
    expect(decodeMessage(lines[1]).message?.kind).toBe("ack");
    transport.close();
    expect(log.child?.killed).toBe(true);
  });

  it("allows an explicit Rust host even when the environment switch is off", () => {
    const log: { command?: string; args?: readonly string[]; options?: HostSpawnOptions; child?: FakeChild } = {};
    const transport = createRustHostTransport({
      command: "/opt/praxis/rust-protocol-host",
      args: ["--test"],
      env: { PRAXIS_RUST_HOST: "0" },
      spawnImpl: fakeFactory(log),
    });
    expect(transport.host).toBe("rust");
    expect(log.command).toBe("/opt/praxis/rust-protocol-host");
    expect(log.args).toEqual(["--test"]);
    transport.close();
  });

  it("fails a pending request immediately when the Rust child exits", async () => {
    const log: { child?: FakeChild } = {};
    const transport = createRustHostTransport({
      timeoutMs: 5_000,
      spawnImpl: fakeFactory(log),
    });
    log.child!.suppressResponses = true;
    const pending = transport(encodeMessage(makeMessage("s", 1, "command", { name: "status" })));
    log.child!.emit("exit", 17, null);
    await expect(pending).rejects.toThrow("protocol rust host exited");
    await expect(transport(encodeMessage(makeMessage("s", 2, "command", { name: "status" })))).rejects.toThrow(
      "protocol rust host exited",
    );
  });

  it("fails pending requests when the managed transport closes", async () => {
    const log: { child?: FakeChild } = {};
    const transport = createRustHostTransport({
      timeoutMs: 5_000,
      spawnImpl: fakeFactory(log),
    });
    log.child!.suppressResponses = true;
    const pending = transport(encodeMessage(makeMessage("s", 1, "command", { name: "status" })));
    transport.close();
    await expect(pending).rejects.toThrow("transport is closed");
    transport.close();
  });
});
