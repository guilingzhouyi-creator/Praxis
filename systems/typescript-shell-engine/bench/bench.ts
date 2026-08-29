/**
 * Micro-benchmark harness for L2 TS engine hot paths.
 *
 * Measures ops/sec with warm-up + measurement phases. Results are compared
 * against recorded baselines to detect performance regressions in CI.
 *
 * - Harness (`bench`, `checkDrift`) is imported by tests/bench.test.ts.
 * - Engine hot-path cases (merged from bench/engine-bench.ts) run standalone:
 *   `node bench/bench.ts` (Node 24+ strips types natively).
 */

import { pathToFileURL } from "node:url";

import { isAckLine } from "../src/engine/transports/line-transport.ts";
import { Dispatcher, type CommandResult, type DispatchContext } from "../src/engine/dispatcher.ts";
import { parseLine, tokenize } from "../src/engine/parser.ts";

export interface BenchResult {
  name: string;
  opsPerSec: number;
  totalMs: number;
  iterations: number;
}

/** Measure ops/sec for a synchronous function over a fixed time budget. */
export function bench(name: string, fn: () => void, budgetMs = 500): BenchResult {
  // Warm-up: run enough iterations to trigger JIT optimisation.
  let warmup = 0;
  const warmStart = performance.now();
  while (performance.now() - warmStart < 50) {
    fn();
    warmup++;
  }

  // Measurement phase.
  const start = performance.now();
  let iterations = 0;
  while (performance.now() - start < budgetMs) {
    fn();
    iterations++;
  }
  const elapsed = performance.now() - start;
  return {
    name,
    opsPerSec: Math.round((iterations / elapsed) * 1000),
    totalMs: Math.round(elapsed),
    iterations,
  };
}

/** Compare a result against a baseline and flag regressions > drift %. */
export function checkDrift(result: BenchResult, baselineOpsPerSec: number, driftPct = 20): string | undefined {
  if (baselineOpsPerSec <= 0) return undefined; // no baseline — skip
  const floor = baselineOpsPerSec * (1 - driftPct / 100);
  if (result.opsPerSec < floor) {
    return `${result.name}: ${result.opsPerSec} ops/s < ${floor.toFixed(0)} (baseline ${baselineOpsPerSec}, drift ${driftPct}%)`;
  }
  return undefined;
}

// ── Engine hot-path benchmark cases (merged from bench/engine-bench.ts) ──────

/** Run the engine hot-path micro-benchmarks and print their results. */
export function runEngineBenchmarks(): void {
  // Baseline implementations (pre-optimization semantics).
  function baselineIsAckLine(line: string): boolean {
    try {
      return JSON.parse(line).kind === "ack";
    } catch {
      return false;
    }
  }

  // Fixtures.
  const RESULT_LINE = JSON.stringify({
    v: 1,
    session_id: "s-1",
    seq: 42,
    ts: 1723812345.678,
    trace_id: "tr-abc",
    kind: "result",
    payload: { success: true, name: "status" },
  });
  const ACK_LINE = JSON.stringify({
    v: 1,
    session_id: "s-1",
    seq: 42,
    ts: 1723812345.678,
    trace_id: "tr-abc",
    kind: "ack",
    payload: { ack_seq: 41 },
  });
  const EVENT_LINE = JSON.stringify({
    v: 1,
    session_id: "s-1",
    seq: 43,
    ts: 1723812345.7,
    kind: "event",
    payload: { name: "session.attached" },
  });

  function measure(label: string, fn: () => void, iterations: number): number {
    const start = performance.now();
    for (let i = 0; i < iterations; i++) fn();
    const elapsed = performance.now() - start;
    const opsPerMs = iterations / elapsed;
    console.log(`${label.padEnd(52)} ${iterations} iters in ${elapsed.toFixed(1)}ms  (${opsPerMs.toFixed(0)} ops/ms)`);
    return opsPerMs;
  }

  const ITERS = 2_000_000;

  console.log("── isAckLine (non-ack lines dominate the hot path) ──────────────");
  // Mix: 90% result/event, 10% ack — approximates a busy interactive session.
  const LINES = [RESULT_LINE, EVENT_LINE, RESULT_LINE, RESULT_LINE, ACK_LINE, EVENT_LINE, RESULT_LINE, EVENT_LINE, RESULT_LINE, RESULT_LINE];
  measure("baseline (JSON.parse every line)", () => {
    for (const line of LINES) baselineIsAckLine(line);
  }, ITERS);
  measure("optimized (substring reject + parse only on match)", () => {
    for (const line of LINES) isAckLine(line);
  }, ITERS);

  console.log("\n── listCommands (help builtin hot path) ─────────────────────────");
  function runDispatcher(build: (d: Dispatcher) => void): number {
    const d = new Dispatcher();
    build(d);
    const start = performance.now();
    for (let i = 0; i < 500_000; i++) d.listCommands();
    return performance.now() - start;
  }
  const makeDispatcher = (d: Dispatcher) => {
    const h = (_args: string[], _ctx: DispatchContext): CommandResult => ({ kind: "local", data: {} });
    for (const name of ["clear", "help", "lang", "memory", "status", "tools", "audit", "chain", "dev", "sys", "setting", "card", "backup", "restore", "shutdown", "boot"]) {
      d.register(name, h);
    }
  };
  const elapsedCached = runDispatcher(makeDispatcher);
  console.log(`optimized (cached sorted listing)            500000 calls in ${elapsedCached.toFixed(1)}ms`);
  // Baseline: a dispatcher that re-sorts on every listCommands call.
  class BaselineDispatcher extends Dispatcher {
    override listCommands(): string[] {
      return [...(this as unknown as { handlers: Map<string, unknown> }).handlers.keys()].sort();
    }
  }
  const elapsedBaseline = runDispatcher((d) => makeDispatcher(d as Dispatcher));
  console.log(`baseline (re-sort per call)                 500000 calls in ${elapsedBaseline.toFixed(1)}ms`);

  console.log("\n── parseLine / tokenize (every input line) ──────────────────────");
  // Structured args: parseLine yields {name, args[]} directly — no second
  // shlex pass, which the Python3 shell needs for its / command path.
  const INPUT_LINES = [
    "status",
    "/status",
    'settings-set llm.model "deepseek-v4-flash"',
    'card "fix the token ring" cell-a',
    "help",
    "memory-digest",
    "cells",
    'model-specs scout',
  ];
  measure("parseLine (structured {name, args})", () => {
    for (const line of INPUT_LINES) parseLine(line);
  }, ITERS);
  measure("tokenize (raw split)", () => {
    for (const line of INPUT_LINES) tokenize(line);
  }, ITERS);
}

// Allow standalone execution: `node bench/bench.ts`.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runEngineBenchmarks();
}
