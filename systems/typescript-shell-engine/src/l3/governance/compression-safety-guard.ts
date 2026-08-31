/**
 * Recursive-compression threshold and circuit-breaker projection.
 *
 * The guard is deliberately independent from a compression implementation.
 * It returns a fail-closed decision and exposes an optional trip callback for
 * an evidence observer; it never persists session payloads or calls Rust.
 */

import {
  L3_GOVERNANCE_DEFAULT_COMPRESSION_BREAKER_ENABLED,
  L3_GOVERNANCE_DEFAULT_COMPRESSION_ERROR_STORM_THRESHOLD,
  L3_GOVERNANCE_DEFAULT_COMPRESSION_ERROR_STORM_WINDOW_SECONDS,
  L3_GOVERNANCE_DEFAULT_COMPRESSION_THRESHOLD,
} from "./governance-limits.ts";

/** Configuration for one compression guard. */
export interface CompressionGuardOptions {
  readonly recursionThreshold?: number;
  readonly breakerEnabled?: boolean;
  readonly errorStormThreshold?: number;
  readonly errorStormWindowSeconds?: number;
  readonly clock?: () => number;
  readonly onTrip?: (reason: string) => void;
}

/** Detached guard state exposed for diagnostics. */
export interface CompressionGuardStatus {
  readonly recursionThreshold: number;
  readonly breakerEnabled: boolean;
  readonly tripped: boolean;
  readonly tripReason: string;
  readonly tripAt: number | null;
  readonly errorStormCount: number;
}

/** Decision returned before a compression pass. */
export interface CompressionGuardDecision {
  readonly success: boolean;
  readonly blocked: boolean;
  readonly error?: string;
}

function requireNonNegativeInteger(value: number, name: string): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative safe integer`);
  }
  return value;
}

function requirePositiveNumber(value: number, name: string): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new TypeError(`${name} must be a positive finite number`);
  }
  return value;
}

/** In-memory compression recursion/error-storm guard. */
export class CompressionGuard {
  private recursionThreshold: number;
  private breakerEnabled: boolean;
  private readonly errorStormThreshold: number;
  private readonly errorStormWindowSeconds: number;
  private readonly clock: () => number;
  private readonly onTrip?: (reason: string) => void;
  private tripped = false;
  private tripReason = "";
  private tripAt: number | null = null;
  private readonly sessionDepth = new Map<string, number>();
  private errorStormCount = 0;
  private errorStormFirst: number | null = null;

  constructor(options: CompressionGuardOptions = {}) {
    this.recursionThreshold = requireNonNegativeInteger(
      options.recursionThreshold ?? L3_GOVERNANCE_DEFAULT_COMPRESSION_THRESHOLD,
      "recursionThreshold",
    );
    this.breakerEnabled = options.breakerEnabled ?? L3_GOVERNANCE_DEFAULT_COMPRESSION_BREAKER_ENABLED;
    this.errorStormThreshold = requirePositiveNumber(
      options.errorStormThreshold ?? L3_GOVERNANCE_DEFAULT_COMPRESSION_ERROR_STORM_THRESHOLD,
      "errorStormThreshold",
    );
    this.errorStormWindowSeconds = requirePositiveNumber(
      options.errorStormWindowSeconds ?? L3_GOVERNANCE_DEFAULT_COMPRESSION_ERROR_STORM_WINDOW_SECONDS,
      "errorStormWindowSeconds",
    );
    this.clock = options.clock ?? (() => Date.now() / 1000);
    this.onTrip = options.onTrip;
  }

  /** Return detached breaker/threshold state. */
  status(): CompressionGuardStatus {
    return {
      recursionThreshold: this.recursionThreshold,
      breakerEnabled: this.breakerEnabled,
      tripped: this.tripped,
      tripReason: this.tripReason,
      tripAt: this.tripAt,
      errorStormCount: this.errorStormCount,
    };
  }

  /** Change operator switches; threshold changes reset tripped state. */
  configure(options: { readonly recursionThreshold?: number; readonly breakerEnabled?: boolean }): void {
    if (options.recursionThreshold !== undefined) {
      this.recursionThreshold = requireNonNegativeInteger(options.recursionThreshold, "recursionThreshold");
      this.reset();
    }
    if (options.breakerEnabled !== undefined) {
      this.breakerEnabled = Boolean(options.breakerEnabled);
      if (!this.breakerEnabled) this.reset();
    }
  }

  /** Check whether a session may start another compression pass. */
  check(sessionId: string): CompressionGuardDecision {
    const id = String(sessionId ?? "");
    if (this.tripped) {
      return {
        success: false,
        blocked: true,
        error: "compression paused by circuit breaker — operator intervention required",
      };
    }
    if (this.breakerEnabled && this.recursionThreshold > 0) {
      const depth = this.sessionDepth.get(id) ?? 0;
      if (depth >= this.recursionThreshold) {
        const reason = `session ${id} reached recursive-compression threshold ${this.recursionThreshold}`;
        this.trip(reason);
        return {
          success: false,
          blocked: true,
          error: `recursive-compression threshold (${this.recursionThreshold}) reached — manual intervention required`,
        };
      }
    }
    return { success: true, blocked: false };
  }

  /** Record one successful compression pass for a session. */
  recordPass(sessionId: string): void {
    const id = String(sessionId ?? "");
    this.sessionDepth.set(id, (this.sessionDepth.get(id) ?? 0) + 1);
    this.errorStormCount = 0;
    this.errorStormFirst = null;
  }

  /** Record a failed pass and trip after an error storm. */
  reportError(sessionId: string): void {
    if (!this.breakerEnabled) return;
    const now = this.clock();
    if (this.errorStormFirst !== null && now - this.errorStormFirst > this.errorStormWindowSeconds) {
      this.errorStormCount = 0;
      this.errorStormFirst = null;
    }
    if (this.errorStormFirst === null) this.errorStormFirst = now;
    this.errorStormCount += 1;
    if (this.errorStormCount >= this.errorStormThreshold) {
      this.trip(
        `compression error storm: ${this.errorStormCount} failures within `
        + `${this.errorStormWindowSeconds}s (session ${String(sessionId ?? "")})`,
      );
    }
  }

  /** Reset all state, including the breaker and per-session depth. */
  reset(): void {
    this.tripped = false;
    this.tripReason = "";
    this.tripAt = null;
    this.sessionDepth.clear();
    this.errorStormCount = 0;
    this.errorStormFirst = null;
  }

  /** Reset only one session's recursion depth. */
  resetSession(sessionId: string): void {
    this.sessionDepth.delete(String(sessionId ?? ""));
  }

  private trip(reason: string): void {
    if (this.tripped) return;
    this.tripped = true;
    this.tripReason = reason;
    this.tripAt = this.clock();
    this.sessionDepth.clear();
    this.errorStormCount = 0;
    this.errorStormFirst = null;
    try {
      this.onTrip?.(reason);
    } catch {
      // Evidence observers are side-channel consumers and cannot break the guard.
    }
  }
}
