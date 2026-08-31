import { describe, expect, it } from "vitest";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  CompressionGuard,
  DurableEvidenceLedger,
  InMemoryEvidenceLedger,
  JsonFileEvidenceStorage,
  MemoryEvidenceStorage,
  ReviewVerifier,
  SensitiveDetector,
  VerificationCommandPort,
  L3GovernanceBoundary,
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

  it("keeps edits pending after a failed verification command", () => {
    const verifier = new ReviewVerifier();
    verifier.recordEdit("src/a.ts");
    verifier.recordCheck("tsc --noEmit", {
      exitCode: 1,
      passed: false,
      evidence: "typecheck failed",
    });
    expect(verifier.canClose()).toMatchObject({ allowed: false, pending: ["src/a.ts"] });
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

  it("recovers durable evidence across restart and rolls back failed commits", () => {
    const storage = new MemoryEvidenceStorage();
    const first = new DurableEvidenceLedger({
      storage,
      ledgerOptions: { maxPoints: 8, maxChains: 4, clock: () => 1 },
    });
    const chainId = first.record({
      phase: "runtime",
      decision: "WARN",
      target: "session-1",
      raw: { step: 1 },
    });
    first.closeChain(chainId, "test complete");

    const restarted = new DurableEvidenceLedger({
      storage,
      ledgerOptions: { maxPoints: 8, maxChains: 4, clock: () => 2 },
    });
    expect(restarted.query({ limit: 1 })[0]).toMatchObject({
      phase: "runtime",
      decision: "WARN",
      chainId,
    });
    expect(restarted.chains()[0]).toMatchObject({ chainId, closed: 1, reason: "test complete" });
    expect(restarted.verify()).toMatchObject({ valid: true, checked: 1 });

    const failingStorage = {
      load: () => storage.load(),
      commit: () => {
        throw new Error("storage unavailable");
      },
    };
    expect(() => new DurableEvidenceLedger({ storage: failingStorage }).record({
      phase: "runtime",
      decision: "BLOCK",
    })).toThrow("storage unavailable");
    expect(restarted.query({ limit: 1 })[0]?.decision).toBe("WARN");
  });

  it("uses an atomic JSON snapshot adapter and rejects tampered restart state", () => {
    const root = mkdtempSync(join(tmpdir(), "praxis-l3-evidence-"));
    const path = join(root, "evidence.json");
    try {
      const storage = new JsonFileEvidenceStorage(path);
      const first = new DurableEvidenceLedger({ storage });
      first.record({ phase: "runtime", decision: "ALLOW", raw: { value: "ok" } });

      const restarted = new DurableEvidenceLedger({ storage });
      expect(restarted.query({ limit: 1 })[0]?.raw).toEqual({ value: "ok" });
      expect(restarted.verify()).toMatchObject({ valid: true, checked: 1 });

      const document = JSON.parse(readFileSync(path, "utf8")) as { lastHash: string };
      document.lastHash = "tampered";
      writeFileSync(path, JSON.stringify(document), "utf8");
      expect(() => new DurableEvidenceLedger({ storage })).toThrow(/last hash|row hash|predecessor/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("validates argv/cwd boundaries before invoking the verification executor", async () => {
    const calls: string[][] = [];
    const port = new VerificationCommandPort({
      projectRoot: "/workspace/praxis",
      executor: {
        async execute(argv) {
          calls.push([...argv]);
          return { exitCode: 0, stdout: "ok", stderr: "" };
        },
      },
    });

    const allowed = await port.run({ argv: ["tsc", "--noEmit"], cwd: "systems" });
    expect(allowed).toMatchObject({ accepted: true, passed: true, exitCode: 0 });
    expect(calls).toEqual([["tsc", "--noEmit"]]);

    const rejectedCommand = await port.run({ argv: ["sh", "-c", "echo unsafe"] });
    expect(rejectedCommand).toMatchObject({ accepted: false, passed: false });
    const rejectedCwd = await port.run({ argv: ["tsc"], cwd: "../escape" });
    expect(rejectedCwd).toMatchObject({ accepted: false, passed: false });
    const rejectedArg = await port.run({ argv: ["tsc", "x".repeat(4097)] });
    expect(rejectedArg).toMatchObject({ accepted: false, passed: false });
    const rejectedLongCwd = await port.run({ argv: ["tsc"], cwd: "x".repeat(1025) });
    expect(rejectedLongCwd).toMatchObject({ accepted: false, passed: false });
    expect(calls).toHaveLength(1);
  });

  it("propagates timeout/cancellation and projects bounded verification evidence", async () => {
    let aborted = false;
    const port = new VerificationCommandPort({
      projectRoot: "/workspace/praxis",
      maxOutputBytes: 32,
      executor: {
        async execute(_argv, options) {
          return new Promise((resolve) => {
            options.signal.addEventListener("abort", () => {
              aborted = true;
              resolve({ exitCode: null, stdout: "x".repeat(100), stderr: "timed" });
            }, { once: true });
          });
        },
      },
    });
    const timedOut = await port.run({ argv: ["tsc"], timeoutMs: 5 });
    expect(timedOut).toMatchObject({ accepted: true, passed: false, timedOut: true });
    expect(aborted).toBe(true);
    expect(new TextEncoder().encode(timedOut.stdout).byteLength).toBeLessThanOrEqual(32);

    const controller = new AbortController();
    controller.abort();
    const cancelled = await port.run({ argv: ["tsc"] }, controller.signal);
    expect(cancelled).toMatchObject({ accepted: false, cancelled: true, passed: false });
  });

  it("feeds verification results into the governance review and evidence side channels", async () => {
    const governance = new L3GovernanceBoundary({
      verification: new VerificationCommandPort({
        projectRoot: "/workspace/praxis",
        executor: {
          async execute() {
            return { exitCode: 0, stdout: "clean", stderr: "" };
          },
        },
      }),
    });
    governance.recordEdit("src/example.ts");
    const result = await governance.runVerification({ argv: ["tsc", "--noEmit"] });
    expect(result.passed).toBe(true);
    expect(governance.canCloseVerification().allowed).toBe(true);
    expect(governance.queryEvidence({ phase: "verify_cadence" }).length).toBeGreaterThan(0);
  });

  it("records a fail-closed evidence point when no verification port is configured", async () => {
    const governance = new L3GovernanceBoundary();
    governance.recordEdit("src/example.ts");
    const result = await governance.runVerification({ argv: ["tsc"] });
    expect(result).toMatchObject({ accepted: false, passed: false });
    expect(governance.queryEvidence({ phase: "verify_cadence" })).not.toHaveLength(0);
    expect(governance.canCloseVerification().allowed).toBe(false);
  });
});
