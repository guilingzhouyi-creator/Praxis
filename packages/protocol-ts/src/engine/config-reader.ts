/**
 * ConfigReader — typed mirror of the Python3 SettingsCenter read surface.
 *
 * The TS engine NEVER writes configuration (single write authority is the
 * Python3 host via settings_set bridge). This reader provides type-safe
 * access to config values that the TS frontend needs for local decisions:
 *   - locale preference (for i18n.ts)
 *   - theme / display preferences (for frontend rendering)
 *   - feature flags (for progressive rollout)
 *
 * Values are fetched via bridge.settingsGet and cached with TTL.
 */

import type { ProtocolBridge } from "./bridge.ts";

export interface ConfigReaderOptions {
  ttlMs?: number;
}

interface CacheEntry {
  value: unknown;
  expiresAt: number;
}

/**
 * Type-safe read-only mirror of the Python3 SettingsCenter.
 *
 * Single write authority stays on the host (`settings_set`); this reader
 * never mutates config and exposes only local decisions (locale, theme,
 * feature flags) via a TTL cache. Host payload shapes vary
 * (`{[key]:value}`, `{value}`, `{output:JSON}`), so all are probed.
 */
export class ConfigReader {
  private cache = new Map<string, CacheEntry>();
  private pending = new Map<string, Promise<string>>();
  private readonly ttlMs: number;

  constructor(
    private readonly bridge: ProtocolBridge,
    { ttlMs = 30_000 }: ConfigReaderOptions = {},
  ) {
    if (!Number.isFinite(ttlMs) || ttlMs < 0) throw new Error("ttlMs must be a non-negative number");
    this.ttlMs = ttlMs;
  }

  /** Read a string config value with TTL cache and request deduplication. */
  async getString(key: string, fallback = ""): Promise<string> {
    if (typeof key !== "string" || key.length === 0) return fallback;
    const cached = this.cache.get(key);
    if (cached && Date.now() < cached.expiresAt) return String(cached.value);
    const inFlight = this.pending.get(key);
    if (inFlight) return inFlight;
    const job = this.fetchString(key, fallback);
    this.pending.set(key, job);
    try {
      return await job;
    } finally {
      this.pending.delete(key);
    }
  }

  /** Invalidate the entire cache (called when the host pushes a config change). */
  invalidate(): void {
    this.cache.clear();
  }

  /** Invalidate a single key (fine-grained push). */
  invalidateKey(key: string): void {
    this.cache.delete(key);
  }

  private async fetchString(key: string, fallback: string): Promise<string> {
    try {
      const messages = await this.bridge.settingsGet(key);
      const payload = messages[0]?.payload as Record<string, unknown> | undefined;
      if (!payload) return fallback;
      // Direct key, common envelope shapes, and JSON-encoded output.
      let raw: unknown = payload[key];
      if (typeof raw !== "string") raw = (payload as Record<string, unknown>).value;
      if (typeof raw !== "string" && typeof payload.output === "string") {
        try {
          const parsed = JSON.parse(payload.output as string) as Record<string, unknown>;
          if (typeof parsed[key] === "string") raw = parsed[key];
          else if (typeof parsed.value === "string") raw = parsed.value;
        } catch {
          // output is plain text — treat it as the value when single-key fetch.
          if (Object.keys(payload).length === 2 && "success" in payload) raw = payload.output;
        }
      }
      if (typeof raw !== "string") return fallback;
      // Do not cache fallback pollution — only cache real values.
      this.cache.set(key, { value: raw, expiresAt: Date.now() + this.ttlMs });
      return raw;
    } catch {
      return fallback;
    }
  }
}
