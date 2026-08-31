import { describe, expect, it } from "vitest";
import {
  CompressionGuard,
  InMemoryEvidenceLedger,
  ReviewVerifier,
  SensitiveDetector,
  type AgentRuntimeEvent,
} from "../src/l3/l3-agent-entry.ts";

describe("TypeScript L3 governance projections", () => {
  it("scans, redacts, and blocks sensitive values without mutating input", () => {
    const detector = new SensitiveDetector({ action: "redact" });
    const source = "token Bearer abcdefghijklmnop and host 192.168.1.10";
    const result = detector.scan(source);

    expect(source).toContain("Bearer");
    expect(result.hits.map((hit) => hit.kind)).toEqual(["bearer", "ipv4"]);
    expect(result.blocked).toBe(false);
    expect(result.text).toContain("[REDACTED:bearer]");
    expect(result.text).toContain("[REDACTED:ipv4]");

    detector.configure({ action: "block" });
    expect(detector.scan(source)).toMatchObject({ blocked: true, action: "block" });
  });

  it("bounds sensitive reports and degrades disabled detection to a no-op", () => {
    const detector = new SensitiveDetector({ maxHits: 1 });
    const result = detector.scan("10.0.0.1 10.0.0.2");
    expect(result.hits).toHaveLength(1);
    expect(result.truncated).toBe(true);

    detector.configure({ enabled: false });
    expect(detector.scan("Bearer abcdefghijklmnop")).toMatchObject({
      enabled: false,
      hits: [],
      blocked: false,
      text: "Bearer abcdefghijklmnop",
    });
  });

  it("trips recursive and error-storm compression guards fail-closed", () => {
    let now = 100;
    const trips: string[] = [];
    const guard = new CompressionGuard({
      recursionThreshold: 2,
      errorStormThreshold: 2,
      errorStormWindowSeconds: 10,
      clock: () => now,
      onTrip: (reason) => trips.push(reason),
    });

    expect(guard.check("session-1")).toMatchObject({ success: true, blocked: false });
    guard.recordPass("session-1");
    expect(guard.check("session-1")).toMatchObject({ success: true, blocked: false });
    guard.recordPass("session-1");
    expect(guard.check("session-1")).toMatchObject({ success: false, blocked: true });
    expect(guard.status()).toMatchObject({ tripped: true, recursionThreshold: 2 });
    expect(trips).toHaveLength(1);

    guard.reset();
    guard.reportError("session-2");
    guard.reportError("session-2");
    expect(guard.status()).toMatchObject({ tripped: true, errorStormCount: 0 });

    guard.reset();
    guard.reportError("session-2");
    now += 11;
    guard.reportError("session-2");
    expect(guard.status()).toMatchObject({ tripped: false, errorStormCount: 1 });
  });

  it("normalizes review responses and escalates after bounded retries", () => {
    const verifier = new ReviewVerifier({ maxRounds: 1 });
    const request = verifier.requestReview("agent-a", "reviewer-b", "review the change");
    const response = verifier.normalizeResponse(request, {
      verdict: "unknown" as never,
      reason: "needs another look",
      suggestions: ["fix one", "fix two"],
    });
    expect(response).toMatchObject({
      reviewId: request.reviewId,
      reviewerId: "reviewer-b",
      verdict: "NEEDS_CHANGES",
    });
    expect(verifier.dispose(response, 0).action).toBe("retry");
    expect(verifier.dispose(response, 1).action).toBe("escalate");
  });

  it("tracks edit verification and bounded evidence", () => {
    const verifier = new ReviewVerifier();
    verifier.recordEdit("src/a.ts");
    expect(verifier.canClose()).toMatchObject({ allowed: false, pending: ["src/a.ts"] });
    expect(verifier.nudge()).toContain("src/a.ts");
    expect(verifier.canClose()).toMatchObject({ allowed: true });
    verifier.recordCheck("tsc --noEmit", {
      exitCode: 0,
      passed: true,
      evidence: "clean",
    });
    expect(verifier.evidenceLog()).toHaveLength(1);
  });

  it("keeps an append-only evidence hash chain and runtime metadata projection", () => {
    let now = 10;
    const ledger = new InMemoryEvidenceLedger({ maxPoints: 2, clock: () => now++ });
    const first = ledger.record({
      phase: "compression",
      decision: "WARN",
      target: "session-1",
      raw: { before: 100 },
    });
    const second = ledger.record({
      phase: "compression",
      decision: "BLOCK",
      target: "session-1",
      raw: { after: 0 },
      chainKind: "policy-bypass",
    });
    expect(first).not.toBe(second);

    const event: AgentRuntimeEvent = {
      contractVersion: 1,
      eventSeq: 1,
      type: "run_failed",
      runId: "run-1",
      traceId: "trace-1",
      identity: {
        agentId: "agent-1",
        cellId: "cell-1",
        sessionId: "session-1",
        terminalId: "terminal-1",
      },
      data: { code: "execution_rejected" },
      ts: 12,
    };
    ledger.recordRuntimeEvent(event);
    expect(ledger.query({ decision: "BLOCK" })).toHaveLength(2);
    expect(ledger.snapshot().retainedPoints).toBe(2);
    expect(ledger.verify()).toMatchObject({ valid: true, checked: 2 });

    const point = ledger.query({ limit: 1 })[0] as { raw: { [key: string]: unknown } };
    point.raw.tampered = true;
    expect(ledger.verify().valid).toBe(true);
  });
});
