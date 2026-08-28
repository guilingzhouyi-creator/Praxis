/**
 * Structured protocol errors with machine-readable codes.
 *
 * Every gate failure, validation rejection, or transport fault produces a
 * `ProtocolError` carrying a stable code that consumers can switch on for
 * retry / escalation decisions. This replaces ad-hoc string matching.
 *
 * TS pattern: discriminated union via readonly `code` field + `cause` chain
 * for error preservation (ES2022 Error.cause).
 */

/** Canonical protocol error codes shared with Python3. */
export const ERROR_CODES = [
  "VALIDATION_FAILED",
  "TRANSPORT_CLOSED",
  "TRANSPORT_TIMEOUT",
  "SCOPE_NOT_REGISTERED",
  "TYPE_CONTENT_MISMATCH",
  "COAUTH_REJECTED",
  "SHARED_FILE_GATE",
  "BRIDGE_UNAVAILABLE",
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

export class ProtocolError extends Error {
  readonly code: ErrorCode;
  /** Whether the caller may safely retry the operation. */
  readonly retryable: boolean;

  constructor(code: ErrorCode, message: string, options?: { cause?: unknown; retryable?: boolean }) {
    super(message, { cause: options?.cause });
    this.code = code;
    this.retryable = options?.retryable ?? false;
    // Restore prototype chain after Error subclassing (TS/ES5 target quirk).
    Object.setPrototypeOf(this, ProtocolError.prototype);
  }

  /** Serialize the error as a wire-safe JSON payload. */
  toJSON(): { code: ErrorCode; message: string; retryable: boolean } {
    return { code: this.code, message: this.message, retryable: this.retryable };
  }
}

/** Exponential backoff with jitter for retryable operations. */
export async function withRetry<T>(
  fn: () => Promise<T>,
  opts: { maxRetries?: number; baseDelayMs?: number; signal?: AbortSignal } = {},
): Promise<T> {
  const maxRetries = opts.maxRetries ?? 3;
  const baseDelay = opts.baseDelayMs ?? 200;
  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (opts.signal?.aborted) throw new ProtocolError("TRANSPORT_CLOSED", "aborted");
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (err instanceof ProtocolError && !err.retryable) throw err;
      if (attempt < maxRetries) {
        const delay = baseDelay * Math.pow(2, attempt) + Math.random() * baseDelay;
        await new Promise<void>((resolve) => setTimeout(resolve, delay));
      }
    }
  }
  throw lastError;
}
