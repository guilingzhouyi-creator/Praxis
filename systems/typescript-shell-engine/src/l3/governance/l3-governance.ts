/**
 * Composition boundary for L3 governance side channels.
 *
 * The boundary combines sensitive scanning, compression protection, review/
 * verification cadence, and bounded evidence projection. It is safe to attach
 * as an AgentEventSink: observer failures are swallowed and cannot change the
 * runtime's Rust admission result.
 */

import type {
  AgentEventSink,
  AgentRuntimeEvent,
} from "../contracts/agent-contracts.ts";
import {
  CompressionGuard,
  type CompressionGuardDecision,
  type CompressionGuardOptions,
  type CompressionGuardStatus,
} from "./compression-safety-guard.ts";
import {
  InMemoryEvidenceLedger,
  type EvidencePort,
  type EvidenceQuery,
  type EvidenceVerification,
} from "./evidence-ledger.ts";
import {
  ReviewVerifier,
  type ReviewVerifierOptions,
  type ReviewRequest,
  type ReviewResponse,
  type ReviewDisposition,
  type VerificationEvidence,
} from "./review-verifier.ts";
import {
  SensitiveDetector,
  type SensitiveDetectorOptions,
  type SensitiveScanResult,
} from "./sensitive-detector.ts";

/** Options for the composed governance observer. */
export interface L3GovernanceOptions {
  readonly evidence?: EvidencePort;
  readonly sensitive?: SensitiveDetectorOptions;
  readonly compression?: CompressionGuardOptions;
  readonly review?: ReviewVerifierOptions;
}

/** Detached aggregate status for operator-facing diagnostics. */
export interface L3GovernanceStatus {
  readonly compression: CompressionGuardStatus;
  readonly evidence: ReturnType<InMemoryEvidenceLedger["snapshot"]> | null;
  readonly sensitive: ReturnType<SensitiveDetector["status"]>;
}

/** Composed L3 governance side-channel boundary. */
export class L3GovernanceBoundary implements AgentEventSink {
  readonly evidence: EvidencePort;
  readonly sensitive: SensitiveDetector;
  readonly compression: CompressionGuard;
  readonly review: ReviewVerifier;

  constructor(options: L3GovernanceOptions = {}) {
    this.evidence = options.evidence ?? new InMemoryEvidenceLedger();
    this.sensitive = new SensitiveDetector(options.sensitive);
    this.compression = options.compression
      ? new CompressionGuard(options.compression)
      : new CompressionGuard({
        onTrip: (reason) => this.safeEvidence({
          phase: "compression_guard",
          gate: "circuit_breaker",
          decision: "BLOCK",
          target: "session_compress",
          source: "ts-l3-governance",
          tags: { reason },
        }),
      });
    this.review = new ReviewVerifier(options.review);
  }

  /** Observe selected runtime events without retaining event payloads. */
  publish(event: AgentRuntimeEvent): void {
    try {
      const candidate = this.evidence as Partial<InMemoryEvidenceLedger>;
      if (typeof candidate.recordRuntimeEvent === "function") {
        candidate.recordRuntimeEvent(event);
      } else if (event.type === "run_failed") {
        this.evidence.record({
          phase: "l3_runtime",
          gate: event.type,
          decision: "BLOCK",
          target: event.type,
          source: "ts-l3-runtime",
        });
      }
    } catch {
      // Evidence is a non-blocking observer and must never break AgentRuntime.
    }
  }

  /** Scan a text span and project only bounded hit metadata to evidence. */
  scanSensitive(text: string): SensitiveScanResult {
    const result = this.sensitive.scan(text);
    if (result.hits.length > 0) {
      this.safeEvidence({
        phase: "sensitive_detect",
        gate: "sensitive_policy",
        decision: result.blocked ? "BLOCK" : result.action === "redact" ? "CHANGE" : "WARN",
        target: "text_span",
        source: "ts-l3-governance",
        tags: {
          action: result.action,
          hit_count: String(result.hits.length),
          truncated: String(result.truncated),
        },
      });
    }
    return result;
  }

  /** Check whether one compression pass may start. */
  checkCompression(sessionId: string): CompressionGuardDecision {
    const decision = this.compression.check(sessionId);
    if (decision.blocked) {
      this.safeEvidence({
        phase: "compression_guard",
        gate: "recursion",
        decision: "BLOCK",
        target: "session_compress",
        source: "ts-l3-governance",
      });
    }
    return decision;
  }

  /** Record a successful compression pass. */
  recordCompressionPass(sessionId: string): void {
    this.compression.recordPass(sessionId);
  }

  /** Report a compression error to the breaker. */
  reportCompressionError(sessionId: string): void {
    this.compression.reportError(sessionId);
  }

  /** Create a detached review request. */
  requestReview(agentId: string, reviewerId: string, task: string): ReviewRequest {
    return this.review.requestReview(agentId, reviewerId, task);
  }

  /** Normalize a response and return its bounded disposition. */
  disposeReview(
    request: ReviewRequest,
    response: Partial<ReviewResponse>,
    retryCount = 0,
  ): ReviewDisposition {
    const normalized = this.review.normalizeResponse(request, response);
    const disposition = this.review.dispose(normalized, retryCount);
    this.safeEvidence({
      phase: "peer_review",
      gate: "review_verdict",
      decision: disposition.action === "pass" ? "ALLOW" : disposition.action === "escalate" ? "BLOCK" : "WARN",
      target: request.reviewId,
      source: "ts-l3-governance",
      tags: { verdict: normalized.verdict, action: disposition.action, round: String(disposition.round) },
    });
    return disposition;
  }

  /** Track an edit awaiting a verifying command. */
  recordEdit(path: string): void {
    this.review.recordEdit(path);
  }

  /** Record a verification result as bounded evidence. */
  recordCheck(command: string, result?: Omit<VerificationEvidence, "command">): void {
    this.review.recordCheck(command, result);
    if (result) {
      this.safeEvidence({
        phase: "verify_cadence",
        gate: "edit_then_verify",
        decision: result.passed ? "ALLOW" : "BLOCK",
        target: "verification",
        source: "ts-l3-governance",
        tags: { command: command.slice(0, 128), exit_code: String(result.exitCode) },
      });
    }
  }

  /** Return a bounded nudge for unverified edits. */
  nudgeVerification(): string | null {
    return this.review.nudge();
  }

  /** Return whether the tracked edit set may be closed. */
  canCloseVerification(): ReturnType<ReviewVerifier["canClose"]> {
    return this.review.canClose();
  }

  /** Return selected evidence without exposing mutable ledger storage. */
  queryEvidence(filter?: EvidenceQuery) {
    return this.evidence.query(filter);
  }

  /** Verify evidence fixity through the injected ledger. */
  verifyEvidence(): EvidenceVerification {
    return this.evidence.verify();
  }

  /** Return aggregate status; custom durable ledgers may omit a snapshot. */
  status(): L3GovernanceStatus {
    const candidate = this.evidence as Partial<InMemoryEvidenceLedger>;
    return {
      compression: this.compression.status(),
      evidence: typeof candidate.snapshot === "function" ? candidate.snapshot() : null,
      sensitive: this.sensitive.status(),
    };
  }

  private safeEvidence(input: Parameters<EvidencePort["record"]>[0]): void {
    try {
      this.evidence.record(input);
    } catch {
      // The evidence chain is best-effort and cannot become a new failure path.
    }
  }
}
