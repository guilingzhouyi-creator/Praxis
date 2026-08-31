/**
 * Safe verification-command boundary for L3 governance.
 *
 * L3 validates an argv-only, allowlisted request and projects bounded output.
 * The executor is injected by the host; this module never invokes a shell,
 * subprocess API, terminal, or process handle directly.
 */

import {
  L3_GOVERNANCE_DEFAULT_VERIFY_TIMEOUT_MS,
  L3_GOVERNANCE_MAX_VERIFY_ARG_BYTES,
  L3_GOVERNANCE_MAX_VERIFY_ARGS,
  L3_GOVERNANCE_MAX_VERIFY_CWD_BYTES,
  L3_GOVERNANCE_MAX_VERIFY_OUTPUT_BYTES,
  L3_GOVERNANCE_MAX_VERIFY_TIMEOUT_MS,
} from "./governance-limits.ts";
import { isAbsolute, relative, resolve, sep } from "node:path";

/** Raw execution result returned by an injected host/Rust adapter. */
export interface VerificationExecutionResult {
  readonly exitCode: number | null;
  readonly stdout?: string;
  readonly stderr?: string;
}

/** Executor seam; implementations own actual process policy and handles. */
export interface VerificationCommandExecutor {
  execute(
    argv: readonly string[],
    options: {
      readonly cwd: string;
      readonly timeoutMs: number;
      readonly signal: AbortSignal;
    },
  ): Promise<VerificationExecutionResult>;
}

/** Input to the argv-only verification boundary. */
export interface VerificationCommandRequest {
  readonly argv: readonly string[];
  readonly cwd?: string;
  readonly timeoutMs?: number;
}

/** Bounded result returned even when validation or execution fails. */
export interface VerificationCommandResult {
  readonly accepted: boolean;
  readonly passed: boolean;
  readonly timedOut: boolean;
  readonly cancelled: boolean;
  readonly exitCode: number;
  readonly argv: readonly string[];
  readonly cwd: string;
  readonly timeoutMs: number;
  readonly stdout: string;
  readonly stderr: string;
  readonly evidence: string;
  readonly error?: string;
}

/** Port consumed by L3; the host owns the actual executor implementation. */
export interface VerificationPort {
  run(request: VerificationCommandRequest, signal?: AbortSignal): Promise<VerificationCommandResult>;
}

/** Options for the validation wrapper. */
export interface VerificationCommandPortOptions {
  readonly executor: VerificationCommandExecutor;
  readonly projectRoot: string;
  readonly allowedCommands?: readonly string[];
  readonly maxArgs?: number;
  readonly maxArgBytes?: number;
  readonly maxOutputBytes?: number;
  readonly maxTimeoutMs?: number;
}

const DEFAULT_ALLOWED_COMMANDS: readonly string[] = [
  "cargo",
  "tsc",
  "make",
  "npm",
  "pytest",
  "mvn",
  "gradle",
  "gcc",
  "clang",
  "dotnet",
  "ruff",
  "black",
  "mypy",
  "pyright",
  "go build",
  "go test",
];

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function boundText(value: unknown, maxBytes: number): string {
  const text = String(value ?? "");
  if (utf8Bytes(text) <= maxBytes) return text;
  return new TextDecoder().decode(new TextEncoder().encode(text).slice(0, maxBytes));
}

function requirePositiveLimit(value: number, name: string, maximum: number): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new TypeError(`${name} must be a safe integer between 1 and ${maximum}`);
  }
  return value;
}

function validateTimeout(value: number, maxTimeoutMs: number): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > maxTimeoutMs) {
    throw new TypeError(`timeoutMs must be a safe integer between 1 and ${maxTimeoutMs}`);
  }
  return value;
}

function cwdWithinRoot(projectRoot: string, cwd: string): string | null {
  const root = resolve(projectRoot);
  const candidate = cwd || ".";
  const resolved = isAbsolute(candidate) ? resolve(candidate) : resolve(root, candidate);
  const escaped = relative(root, resolved);
  if (escaped === ".." || escaped.startsWith(`..${sep}`) || isAbsolute(escaped)) {
    return null;
  }
  return resolved;
}

function commandAllowed(argv: readonly string[], allowed: ReadonlySet<string>): boolean {
  const first = argv[0] ?? "";
  const pair = argv.length > 1 ? `${first} ${argv[1]}` : first;
  return allowed.has(first) || allowed.has(pair);
}

function detachedArgv(argv: readonly string[]): readonly string[] {
  return argv.map((item) => String(item));
}

/**
 * Validates and executes an allowlisted verification request through an
 * injected executor.
 */
export class VerificationCommandPort implements VerificationPort {
  private readonly executor: VerificationCommandExecutor;
  private readonly projectRoot: string;
  private readonly allowedCommands: ReadonlySet<string>;
  private readonly maxArgs: number;
  private readonly maxArgBytes: number;
  private readonly maxOutputBytes: number;
  private readonly maxTimeoutMs: number;

  constructor(options: VerificationCommandPortOptions) {
    if (!options?.executor || !options.projectRoot) {
      throw new TypeError("verification command executor and projectRoot are required");
    }
    this.executor = options.executor;
    const resolvedRoot = resolve(options.projectRoot);
    if (utf8Bytes(resolvedRoot) > L3_GOVERNANCE_MAX_VERIFY_CWD_BYTES) {
      throw new TypeError("projectRoot exceeds the configured byte bound");
    }
    this.projectRoot = resolvedRoot;
    this.allowedCommands = new Set(
      (options.allowedCommands ?? DEFAULT_ALLOWED_COMMANDS).map((command) => String(command).trim()).filter(Boolean),
    );
    this.maxArgs = requirePositiveLimit(
      options.maxArgs ?? L3_GOVERNANCE_MAX_VERIFY_ARGS,
      "maxArgs",
      L3_GOVERNANCE_MAX_VERIFY_ARGS,
    );
    this.maxArgBytes = requirePositiveLimit(
      options.maxArgBytes ?? L3_GOVERNANCE_MAX_VERIFY_ARG_BYTES,
      "maxArgBytes",
      L3_GOVERNANCE_MAX_VERIFY_ARG_BYTES,
    );
    this.maxOutputBytes = requirePositiveLimit(
      options.maxOutputBytes ?? L3_GOVERNANCE_MAX_VERIFY_OUTPUT_BYTES,
      "maxOutputBytes",
      L3_GOVERNANCE_MAX_VERIFY_OUTPUT_BYTES,
    );
    this.maxTimeoutMs = requirePositiveLimit(
      options.maxTimeoutMs ?? L3_GOVERNANCE_MAX_VERIFY_TIMEOUT_MS,
      "maxTimeoutMs",
      L3_GOVERNANCE_MAX_VERIFY_TIMEOUT_MS,
    );
  }

  /** Validate and run one request without invoking a shell. */
  async run(request: VerificationCommandRequest, signal?: AbortSignal): Promise<VerificationCommandResult> {
    const argv = Array.isArray(request?.argv) ? detachedArgv(request.argv) : [];
    const requestedCwd = String(request?.cwd ?? ".");
    const timeoutMs = request?.timeoutMs === undefined
      ? L3_GOVERNANCE_DEFAULT_VERIFY_TIMEOUT_MS
      : Number.isSafeInteger(request.timeoutMs) ? request.timeoutMs : 0;
    const cwd = utf8Bytes(requestedCwd) <= L3_GOVERNANCE_MAX_VERIFY_CWD_BYTES
      ? cwdWithinRoot(this.projectRoot, requestedCwd)
      : null;
    const validationError = this.validate(argv, timeoutMs, cwd, requestedCwd);
    if (validationError) {
      return this.failure(argv, timeoutMs, cwd ?? this.projectRoot, validationError);
    }
    if (signal?.aborted) {
      return this.failure(argv, timeoutMs, cwd!, "verification was cancelled before execution", true);
    }

    const controller = new AbortController();
    let timedOut = false;
    let cancelled = false;
    const onAbort = () => {
      cancelled = true;
      controller.abort(signal?.reason);
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort(new Error("verification timed out"));
    }, timeoutMs);
    try {
      const raw = await this.executor.execute(argv, {
        cwd: cwd!,
        timeoutMs,
        signal: controller.signal,
      });
      const exitCode = Number.isSafeInteger(raw.exitCode) ? Number(raw.exitCode) : -1;
      const stdout = boundText(raw.stdout, this.maxOutputBytes);
      const stderr = boundText(raw.stderr, this.maxOutputBytes);
      const passed = !timedOut && !cancelled && exitCode === 0;
      return {
        accepted: true,
        passed,
        timedOut,
        cancelled,
        exitCode,
        argv,
        cwd: cwd!,
        timeoutMs,
        stdout,
        stderr,
        evidence: this.evidence(exitCode, timedOut, cancelled, stdout, stderr),
      };
    } catch (error) {
      const message = boundText(
        error instanceof Error ? error.message : "verification executor failed",
        this.maxOutputBytes,
      );
      return {
        accepted: true,
        passed: false,
        timedOut,
        cancelled,
        exitCode: -1,
        argv,
        cwd: cwd!,
        timeoutMs,
        stdout: "",
        stderr: message,
        evidence: this.evidence(-1, timedOut, cancelled, "", message),
        error: message,
      };
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }

  private validate(
    argv: readonly string[],
    timeoutMs: number,
    cwd: string | null,
    requestedCwd: string,
  ): string | null {
    if (argv.length === 0) return "argv must contain a verification command";
    if (argv.length > this.maxArgs) return "argv exceeds the configured argument bound";
    if (argv.some((item) => item.length === 0 || item.includes("\0"))) {
      return "argv entries must be non-empty and NUL-free";
    }
    if (argv.some((item) => utf8Bytes(item) > this.maxArgBytes)) {
      return "argv entry exceeds the configured byte bound";
    }
    if (!commandAllowed(argv, this.allowedCommands)) return `verification command is not allowlisted: ${argv[0]}`;
    if (utf8Bytes(requestedCwd) > L3_GOVERNANCE_MAX_VERIFY_CWD_BYTES) {
      return "verification cwd exceeds the configured byte bound";
    }
    if (cwd === null) return "verification cwd escapes the project root";
    if (utf8Bytes(cwd) > L3_GOVERNANCE_MAX_VERIFY_CWD_BYTES) {
      return "resolved verification cwd exceeds the configured byte bound";
    }
    try {
      validateTimeout(timeoutMs, this.maxTimeoutMs);
    } catch (error) {
      return error instanceof Error ? error.message : "invalid verification timeout";
    }
    return null;
  }

  private failure(
    argv: readonly string[],
    timeoutMs: number,
    cwd: string,
    error: string,
    cancelled = false,
  ): VerificationCommandResult {
    const message = boundText(error, this.maxOutputBytes);
    return {
      accepted: false,
      passed: false,
      timedOut: false,
      cancelled,
      exitCode: -1,
      argv,
      cwd,
      timeoutMs,
      stdout: "",
      stderr: message,
      evidence: `rejected: ${message}`,
      error: message,
    };
  }

  private evidence(
    exitCode: number,
    timedOut: boolean,
    cancelled: boolean,
    stdout: string,
    stderr: string,
  ): string {
    const status = timedOut ? "timeout" : cancelled ? "cancelled" : `exit ${exitCode}`;
    const detail = stderr || stdout;
    return boundText(detail ? `${status} | ${detail}` : status, this.maxOutputBytes);
  }
}
