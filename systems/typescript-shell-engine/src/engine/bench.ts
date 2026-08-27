/**
 * Micro-benchmark harness for L2 TS engine hot paths.
 *
 * Measures ops/sec with warm-up + measurement phases. Results are compared
 * against recorded baselines to detect performance regressions in CI.
 * Run standalone: `npx vitest run --reporter=verbose tests/bench.test.ts`
 */

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
