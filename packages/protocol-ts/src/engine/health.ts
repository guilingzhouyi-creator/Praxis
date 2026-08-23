/**
 * Bridge health probe — periodic ping to detect host availability.
 *
 * Sends a lightweight status command and measures round-trip latency.
 * Consumers use the result to enable/disable UI elements or trigger
 * reconnection flows. Designed as a standalone utility that composes
 * with any Transport implementation.
 */

import { ProtocolBridge } from "./bridge.ts";
import { ProtocolError } from "./errors.ts";

export interface HealthResult {
  healthy: boolean;
  latencyMs: number;
  error?: string;
}

export class HealthProbe {
  private timer: ReturnType<typeof setInterval> | undefined;
  private lastResult: HealthResult = { healthy: false, latencyMs: -1 };

  constructor(
    private readonly bridge: ProtocolBridge,
    private readonly intervalMs = 30_000,
  ) {}

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => void this.probe(), this.intervalMs);
    void this.probe(); // immediate first check
  }

  stop(): void {
    clearInterval(this.timer);
    this.timer = undefined;
  }

  get latest(): HealthResult {
    return this.lastResult;
  }

  async probe(): Promise<HealthResult> {
    const start = performance.now();
    try {
      await this.bridge.systemStatus();
      this.lastResult = { healthy: true, latencyMs: Math.round(performance.now() - start) };
    } catch (err) {
      this.lastResult = {
        healthy: false,
        latencyMs: Math.round(performance.now() - start),
        error: err instanceof Error ? err.message : String(err),
      };
    }
    return this.lastResult;
  }
}
