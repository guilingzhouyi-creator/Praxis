/**
 * Data-only peer-review and edit-then-verify projections.
 *
 * Review decisions are bounded values. No LLM, subprocess, file-system, or
 * process handle is created here; those mechanisms remain host-injected and
 * Rust-gated where they can cause side effects.
 */

import {
  L3_GOVERNANCE_DEFAULT_REVIEW_MAX_ROUNDS,
  L3_GOVERNANCE_MAX_REVIEW_SUGGESTIONS,
  L3_GOVERNANCE_MAX_REVIEW_TEXT,
  L3_GOVERNANCE_MAX_VERIFY_EVIDENCE,
  L3_GOVERNANCE_MAX_VERIFY_PATHS,
  L3_GOVERNANCE_MAX_VERIFY_TEXT,
} from "./governance-limits.ts";

/** Stable review verdict vocabulary. */
export type ReviewVerdict = "PASS" | "NEEDS_CHANGES" | "REJECT";
/** Next action after a review verdict. */
export type ReviewAction = "pass" | "retry" | "escalate";

/** Bounded review request value. */
export interface ReviewRequest {
  readonly reviewId: string;
  readonly agentId: string;
  readonly reviewerId: string;
  readonly task: string;
}

/** Bounded review response value. */
export interface ReviewResponse {
  readonly reviewId: string;
  readonly reviewerId: string;
  readonly verdict: ReviewVerdict;
  readonly reason: string;
  readonly suggestions: readonly string[];
}

/** Review transition result. */
export interface ReviewDisposition {
  readonly action: ReviewAction;
  readonly round: number;
  readonly correctionPrompt: string;
  readonly reason?: string;
}

/** One deterministic verification evidence entry. */
export interface VerificationEvidence {
  readonly command: string;
  readonly exitCode: number;
  readonly passed: boolean;
  readonly evidence: string;
}

/** Options for the review/cadence projection. */
export interface ReviewVerifierOptions {
  readonly maxRounds?: number;
  readonly verifyCommands?: readonly string[];
  readonly maxVerifyPaths?: number;
  readonly maxVerifyEvidence?: number;
}

function boundedText(value: unknown, maxChars: number): string {
  const text = String(value ?? "");
  return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text;
}

function requirePositiveLimit(value: number, name: string): number {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

/** Review state machine plus edit-then-verify tracking. */
export class ReviewVerifier {
  private readonly maxRounds: number;
  private readonly verifyCommands: ReadonlySet<string>;
  private readonly maxVerifyPaths: number;
  private readonly maxVerifyEvidence: number;
  private readonly edited = new Set<string>();
  private readonly nudged = new Set<string>();
  private readonly evidence: VerificationEvidence[] = [];
  private reviewCounter = 0;

  constructor(options: ReviewVerifierOptions = {}) {
    this.maxRounds = requirePositiveLimit(
      options.maxRounds ?? L3_GOVERNANCE_DEFAULT_REVIEW_MAX_ROUNDS,
      "maxRounds",
    );
    this.verifyCommands = new Set((options.verifyCommands ?? [
      "cargo",
      "tsc",
      "make",
      "npm",
      "pytest",
      "ruff",
      "mypy",
      "pyright",
      "go build",
      "go test",
    ]).map((command) => String(command).trim()).filter(Boolean));
    this.maxVerifyPaths = requirePositiveLimit(
      options.maxVerifyPaths ?? L3_GOVERNANCE_MAX_VERIFY_PATHS,
      "maxVerifyPaths",
    );
    this.maxVerifyEvidence = requirePositiveLimit(
      options.maxVerifyEvidence ?? L3_GOVERNANCE_MAX_VERIFY_EVIDENCE,
      "maxVerifyEvidence",
    );
  }

  /** Create a bounded review request without dispatching it. */
  requestReview(agentId: string, reviewerId: string, task: string): ReviewRequest {
    this.reviewCounter += 1;
    return {
      reviewId: `review-${this.reviewCounter}`,
      agentId: boundedText(agentId, L3_GOVERNANCE_MAX_REVIEW_TEXT),
      reviewerId: boundedText(reviewerId, L3_GOVERNANCE_MAX_REVIEW_TEXT),
      task: boundedText(task, L3_GOVERNANCE_MAX_REVIEW_TEXT),
    };
  }

  /** Normalize an untrusted review response into a detached value. */
  normalizeResponse(request: ReviewRequest, response: Partial<ReviewResponse>): ReviewResponse {
    const verdict = String(response.verdict ?? "NEEDS_CHANGES").toUpperCase();
    const normalized: ReviewVerdict =
      verdict === "PASS" || verdict === "REJECT" || verdict === "NEEDS_CHANGES"
        ? verdict
        : "NEEDS_CHANGES";
    const suggestions = Array.isArray(response.suggestions)
      ? response.suggestions
        .slice(0, L3_GOVERNANCE_MAX_REVIEW_SUGGESTIONS)
        .map((item) => boundedText(item, L3_GOVERNANCE_MAX_REVIEW_TEXT))
      : [];
    return {
      reviewId: request.reviewId,
      reviewerId: boundedText(response.reviewerId ?? request.reviewerId, L3_GOVERNANCE_MAX_REVIEW_TEXT),
      verdict: normalized,
      reason: boundedText(response.reason, L3_GOVERNANCE_MAX_REVIEW_TEXT),
      suggestions,
    };
  }

  /** Apply the bounded retry/escalation transition for one response. */
  dispose(response: ReviewResponse, retryCount = 0): ReviewDisposition {
    const round = requirePositiveLimit(retryCount + 1, "retryCount + 1");
    if (response.verdict === "PASS") {
      return { action: "pass", round, correctionPrompt: "" };
    }
    const correctionPrompt = boundedText(
      `Review ${response.verdict}: ${response.reason}`,
      L3_GOVERNANCE_MAX_REVIEW_TEXT,
    );
    if (response.verdict === "REJECT" || retryCount >= this.maxRounds) {
      return {
        action: "escalate",
        round,
        correctionPrompt,
        reason: `Review ${response.verdict} after ${retryCount} rounds`,
      };
    }
    return { action: "retry", round: retryCount + 1, correctionPrompt };
  }

  /** Mark a path as edited and pending a verifying check. */
  recordEdit(path: string): void {
    const bounded = boundedText(path, L3_GOVERNANCE_MAX_VERIFY_TEXT);
    if (!bounded || this.edited.size >= this.maxVerifyPaths) return;
    this.edited.add(bounded);
  }

  /** Record a check; recognized verifier commands clear pending edits. */
  recordCheck(command: string, result?: Omit<VerificationEvidence, "command">): void {
    const boundedCommand = boundedText(command, L3_GOVERNANCE_MAX_VERIFY_TEXT);
    if (this.isVerifying(boundedCommand)) this.edited.clear();
    if (!result || this.evidence.length >= this.maxVerifyEvidence) return;
    this.evidence.push({
      command: boundedCommand,
      exitCode: Number.isSafeInteger(result.exitCode) ? result.exitCode : -1,
      passed: Boolean(result.passed),
      evidence: boundedText(result.evidence, L3_GOVERNANCE_MAX_VERIFY_TEXT),
    });
  }

  /** Return a nudge for edits that have not yet been verified. */
  nudge(): string | null {
    const unverified = [...this.edited].filter((path) => !this.nudged.has(path));
    if (unverified.length === 0) return null;
    for (const path of unverified) this.nudged.add(path);
    return boundedText(
      `Unverified edits detected:\n${unverified.slice(0, 3).map((path) => `  - ${path}`).join("\n")}\n`
      + "Run a fast verification command before closing the work item.",
      L3_GOVERNANCE_MAX_VERIFY_TEXT,
    );
  }

  /** Return whether no edit remains outside the verification set. */
  canClose(): { readonly allowed: boolean; readonly pending: readonly string[] } {
    const pending = [...this.edited].filter((path) => !this.nudged.has(path));
    return { allowed: pending.length === 0, pending };
  }

  /** Return detached verification evidence. */
  evidenceLog(): readonly VerificationEvidence[] {
    return this.evidence.map((entry) => ({ ...entry }));
  }

  /** Reset review/cadence state. */
  reset(): void {
    this.edited.clear();
    this.nudged.clear();
    this.evidence.length = 0;
    this.reviewCounter = 0;
  }

  private isVerifying(command: string): boolean {
    const first = command.trim().split(/\s+/u)[0] ?? "";
    return this.verifyCommands.has(first) || this.verifyCommands.has(command.trim());
  }
}
