/**
 * Child-process host transports for the protocol-v1 bridge.
 *
 * The Rust host is an opt-in clean-break L1 candidate. This module owns only
 * process wiring and stderr capture; envelope validation, routing authority,
 * sessions, outboxes, and capability policy remain host-owned. The same
 * factory can launch the Python reference host for an explicit rollback path.
 */

import { spawn as nodeSpawn } from "node:child_process";
import path from "node:path";

import type { Transport } from "../bridge.ts";
import { createStdioTransport } from "./stdio.ts";

/** Host implementation selected by the configuration boundary. */
export type HostImplementation = "python" | "rust";

/** Minimal child-process surface required by the transport (easy to inject in tests). */
export interface ChildProcessLike {
  stdin: { write(data: string): void; end?: () => void };
  stdout: unknown;
  stderr: { on?: (event: string, listener: (...args: unknown[]) => void) => unknown };
  on(event: string, listener: (...args: unknown[]) => void): unknown;
  kill(signal?: string): boolean;
}

/** Spawn options accepted by the process factory. */
export interface HostSpawnOptions {
  cwd: string;
  env: NodeJS.ProcessEnv;
  stdio: ["pipe", "pipe", "pipe"];
}

/** Injectable spawn function for deterministic process-lifecycle tests. */
export type SpawnImplementation = (
  command: string,
  args: readonly string[],
  options: HostSpawnOptions,
) => ChildProcessLike;

/** Options shared by Rust and Python child-process hosts. */
export interface HostTransportOptions {
  /** Override host selection; omitted means PRAXIS_RUST_HOST decides. */
  host?: HostImplementation;
  /** Explicit executable override (otherwise host-specific defaults apply). */
  command?: string;
  /** Explicit argv override (otherwise host-specific defaults apply). */
  args?: readonly string[];
  /** Working directory override. */
  cwd?: string;
  /** Environment overlay; process.env remains the base. */
  env?: NodeJS.ProcessEnv;
  /** Maximum response lines per request (default 256). */
  maxLines?: number;
  /** Idle timeout between response lines in ms (default 5000). */
  timeoutMs?: number;
  /** Maximum UTF-8 bytes accepted for one wire frame (default 1 MiB). */
  maxFrameBytes?: number;
  /** Injectable process launcher. */
  spawnImpl?: SpawnImplementation;
}

/** A Transport with explicit child lifecycle and diagnostic accessors. */
export type ManagedHostTransport = Transport & {
  readonly host: HostImplementation;
  readonly child: ChildProcessLike;
  /** Stop the child and close its stdin. Safe to call more than once. */
  close: () => void;
  /** Return stderr captured since process start. */
  stderrText: () => string;
};

const DEFAULT_CWD = process.cwd();

/**
 * Resolve the Rust host command without coupling the TS engine to a checkout.
 *
 * The executable is supplied by the caller/environment and may be installed
 * on PATH, container-mounted, or provisioned by a separate build pipeline.
 * Keeping this a command name (rather than a repo-relative path) preserves
 * the three-system boundary: TypeScript does not depend on the Rust tree.
 */
export function defaultRustHostBinary(env: NodeJS.ProcessEnv = process.env): string {
  return env.PRAXIS_RUST_HOST_BIN?.trim() || "rust-protocol-host";
}

/** Return whether the explicit Rust host switch is enabled. */
export function isRustHostEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  const value = env.PRAXIS_RUST_HOST?.trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on" || value === "rust";
}

/** Resolve the configured host, defaulting to the Python rollback path. */
export function resolveHostImplementation(env: NodeJS.ProcessEnv = process.env): HostImplementation {
  return isRustHostEnabled(env) ? "rust" : "python";
}

function spawnSpec(options: HostTransportOptions, host: HostImplementation, env: NodeJS.ProcessEnv): {
  command: string;
  args: readonly string[];
  cwd: string;
} {
  if (options.command) {
    return {
      command: options.command,
      args: options.args ?? [],
      cwd: options.cwd ?? DEFAULT_CWD,
    };
  }
  if (host === "rust") {
    return {
      command: defaultRustHostBinary(env),
      args: options.args ?? [],
      cwd: options.cwd ?? DEFAULT_CWD,
    };
  }
  return {
    command: env.PRAXIS_PYTHON ?? "python",
    args: options.args ?? ["-m", "l2.protocol"],
    cwd: options.cwd ?? env.PRAXIS_PYTHON_HOST_CWD ?? DEFAULT_CWD,
  };
}

/** Spawn one configured protocol host and return a managed line transport. */
export function createHostTransport(options: HostTransportOptions = {}): ManagedHostTransport {
  const env = { ...process.env, ...options.env };
  const host = options.host ?? resolveHostImplementation(env);
  const spec = spawnSpec(options, host, env);
  const spawnImpl = options.spawnImpl ?? ((command, args, spawnOptions) =>
    nodeSpawn(command, [...args], spawnOptions) as unknown as ChildProcessLike);
  const child = spawnImpl(spec.command, spec.args, {
    cwd: spec.cwd,
    env,
    stdio: ["pipe", "pipe", "pipe"],
  });

  let closed = false;
  let processError: Error | undefined;
  let failPending: ((error: unknown) => void) | undefined;
  let stderr = "";
  child.stderr.on?.("data", (chunk: unknown) => {
    stderr += String(chunk);
  });
  const recordProcessError = (error: unknown): void => {
    if (closed || processError) return;
    processError = error instanceof Error ? error : new Error(String(error));
    failPending?.(processError);
  };
  child.on("error", recordProcessError);
  child.on("exit", (code: unknown, signal: unknown) => {
    if (!closed && !processError) {
      recordProcessError(new Error(`protocol ${host} host exited (code=${String(code)}, signal=${String(signal)})`));
    }
  });

  const transport = createStdioTransport({
    input: child.stdout,
    onError: (handler) => {
      failPending = handler;
    },
    output: {
      write: (line: string) => {
        if (processError) throw processError;
        if (closed) throw new Error(`protocol ${host} host transport is closed`);
        child.stdin.write(line);
      },
    },
    maxLines: options.maxLines,
    timeoutMs: options.timeoutMs,
    maxFrameBytes: options.maxFrameBytes,
  });

  const managed = transport as ManagedHostTransport;
  Object.defineProperties(managed, {
    host: { value: host, enumerable: true },
    child: { value: child, enumerable: true },
    close: {
      enumerable: true,
      value: () => {
        if (closed) return;
        closed = true;
        failPending?.(new Error(`protocol ${host} host transport is closed`));
        child.stdin.end?.();
        child.kill();
      },
    },
    stderrText: { enumerable: true, value: () => stderr },
  });
  return managed;
}

/** Spawn the Rust host explicitly, bypassing the environment switch. */
export function createRustHostTransport(options: Omit<HostTransportOptions, "host"> = {}): ManagedHostTransport {
  return createHostTransport({ ...options, host: "rust" });
}

/** Spawn the selected host; Rust is used only when PRAXIS_RUST_HOST is enabled. */
export function createConfiguredHostTransport(options: Omit<HostTransportOptions, "host"> = {}): ManagedHostTransport {
  return createHostTransport(options);
}
