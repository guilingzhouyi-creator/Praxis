/**
 * Read-only sensitive-information detection for L3 side-channel projections.
 *
 * The detector is a bounded heuristic, not a secret vault. It never mutates
 * admitted runtime input and does not grant or revoke Rust execution rights.
 */

import {
  L3_GOVERNANCE_MAX_SENSITIVE_FRAGMENT,
  L3_GOVERNANCE_MAX_SENSITIVE_HITS,
} from "./governance-limits.ts";

/** Supported heuristic match classes. */
export type SensitiveKind = "api_key" | "bearer" | "private_key" | "ipv4" | "ipv6";

/** Action applied when one or more sensitive matches are found. */
export type SensitiveAction = "report" | "redact" | "block";

/** One bounded match returned by the detector. */
export interface SensitiveHit {
  readonly kind: SensitiveKind;
  readonly fragment: string;
  readonly index: number;
}

/** Result of scanning one text value. */
export interface SensitiveScanResult {
  readonly enabled: boolean;
  readonly hits: readonly SensitiveHit[];
  readonly truncated: boolean;
  readonly action: SensitiveAction;
  readonly blocked: boolean;
  readonly text: string;
}

/** Configurable, stateless sensitive-information detector. */
export interface SensitiveDetectorOptions {
  readonly enabled?: boolean;
  readonly action?: SensitiveAction;
  readonly maxHits?: number;
  readonly maxFragmentChars?: number;
}

interface PatternDefinition {
  readonly kind: SensitiveKind;
  readonly pattern: RegExp;
}

const PATTERNS: readonly PatternDefinition[] = [
  { kind: "api_key", pattern: /\b(?:sk|pk|ghp|gho|AKIA)[-_A-Za-z0-9]{12,}\b/g },
  { kind: "bearer", pattern: /\bBearer\s+[A-Za-z0-9._~+/=-]{16,}/gi },
  { kind: "private_key", pattern: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/g },
  { kind: "ipv4", pattern: /\b(?:\d{1,3}\.){3}\d{1,3}\b/g },
  { kind: "ipv6", pattern: /\b(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{1,4}\b/g },
];

function requirePositiveLimit(value: number, name: string): number {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function fragment(value: string, maxChars: number): string {
  return value.length > maxChars ? `${value.slice(0, maxChars)}…` : value;
}

function redactMatches(text: string): string {
  let redacted = text;
  for (const definition of PATTERNS) {
    definition.pattern.lastIndex = 0;
    redacted = redacted.replace(
      definition.pattern,
      (_match: string) => `[REDACTED:${definition.kind}]`,
    );
  }
  return redacted;
}

/**
 * Detect and optionally redact sensitive patterns without throwing.
 *
 * Pattern failures degrade to an empty hit set and preserve the original
 * string, matching the Python reference's side-channel behavior.
 */
export class SensitiveDetector {
  private enabled: boolean;
  private action: SensitiveAction;
  private readonly maxHits: number;
  private readonly maxFragmentChars: number;

  constructor(options: SensitiveDetectorOptions = {}) {
    this.enabled = options.enabled ?? true;
    this.action = options.action ?? "report";
    this.maxHits = requirePositiveLimit(
      options.maxHits ?? L3_GOVERNANCE_MAX_SENSITIVE_HITS,
      "maxHits",
    );
    this.maxFragmentChars = requirePositiveLimit(
      options.maxFragmentChars ?? L3_GOVERNANCE_MAX_SENSITIVE_FRAGMENT,
      "maxFragmentChars",
    );
    this.validateAction(this.action);
  }

  /** Return the current detector configuration. */
  status(): { readonly enabled: boolean; readonly action: SensitiveAction } {
    return { enabled: this.enabled, action: this.action };
  }

  /** Update operator-facing switches without touching runtime input. */
  configure(options: Partial<SensitiveDetectorOptions>): void {
    if (options.action !== undefined) this.validateAction(options.action);
    if (options.enabled !== undefined) this.enabled = Boolean(options.enabled);
    if (options.action !== undefined) this.action = options.action;
  }

  /** Scan text and return a bounded, detached result. */
  scan(text: string): SensitiveScanResult {
    const source = String(text ?? "");
    if (!this.enabled || source.length === 0) {
      return {
        enabled: this.enabled,
        hits: [],
        truncated: false,
        action: this.action,
        blocked: false,
        text: source,
      };
    }
    const hits: SensitiveHit[] = [];
    let truncated = false;
    try {
      for (const definition of PATTERNS) {
        definition.pattern.lastIndex = 0;
        for (const match of source.matchAll(definition.pattern)) {
          if (hits.length >= this.maxHits) {
            truncated = true;
            break;
          }
          hits.push({
            kind: definition.kind,
            fragment: fragment(match[0], this.maxFragmentChars),
            index: match.index ?? 0,
          });
        }
        if (truncated) break;
      }
    } catch {
      return {
        enabled: this.enabled,
        hits: [],
        truncated: false,
        action: this.action,
        blocked: false,
        text: source,
      };
    }
    const redacted = this.action === "redact" && hits.length > 0 ? redactMatches(source) : source;
    return {
      enabled: this.enabled,
      hits,
      truncated,
      action: this.action,
      blocked: this.action === "block" && hits.length > 0,
      text: redacted,
    };
  }

  private validateAction(action: string): asserts action is SensitiveAction {
    if (action !== "report" && action !== "redact" && action !== "block") {
      throw new TypeError("action must be one of: report, redact, block");
    }
  }
}
