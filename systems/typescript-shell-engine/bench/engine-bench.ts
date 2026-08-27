/**
 * Engine hot-path micro-benchmarks.
 *
 * Run: node bench/engine-bench.ts   (Node 24+ strips types natively)
 *
 * Compares the optimized implementations against the pre-optimization
 * baseline so the performance advantage of the TS engine is evidenced:
 *   - isAckLine: fast substring reject vs full JSON.parse per line
 *   - listCommands: cached sorted listing vs re-sort per call
 */

import { isAckLine } from "../src/engine/transports/line-transport.ts";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import type { CommandResult, DispatchContext } from "../src/engine/dispatcher.ts";

// ── baseline implementations (pre-optimization semantics) ────────────────────
function baselineIsAckLine(line: string): boolean {
  try {
    return JSON.parse(line).kind === "ack";
  } catch {
    return false;
  }
}

// ── fixtures ─────────────────────────────────────────────────────────────────
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

function bench(label: string, fn: () => void, iterations: number): number {
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
bench("baseline (JSON.parse every line)", () => {
  for (const line of LINES) baselineIsAckLine(line);
}, ITERS);
bench("optimized (substring reject + parse only on match)", () => {
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
import { parseLine, tokenize } from "../src/engine/parser.ts";

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
bench("parseLine (structured {name, args})", () => {
  for (const line of INPUT_LINES) parseLine(line);
}, ITERS);
bench("tokenize (raw split)", () => {
  for (const line of INPUT_LINES) tokenize(line);
}, ITERS);
