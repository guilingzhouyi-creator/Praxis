/**
 * ConfigReader — typed mirror of the Python3 SettingsCenter read surface.
 *
 * The TS engine NEVER writes configuration (single write authority is the
 * Python3 host via settings_set bridge). This reader provides type-safe
 * access to config values that the TS frontend needs for local decisions:
 *   - locale preference (for locale-catalog.ts)
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
 * never mutates config and exposes only local decisions via a TTL cache.
 */
export class ConfigReader {
  private cache = new Map<string, CacheEntry>();
  private readonly ttlMs: number;

  constructor(
    private readonly bridge: ProtocolBridge,
    opts: ConfigReaderOptions = {},
  ) {
    this.ttlMs = opts.ttlMs ?? 30_000;
  }

  /** Read a string config value with TTL cache. */
  async getString(key: string, fallback = ""): Promise<string> {
    if (!key) return fallback;
    const cached = this.cache.get(key);
    if (cached && Date.now() < cached.expiresAt) return String(cached.value);
    try {
      const payload = (await this.bridge.settingsGet(key))[0]?.payload as
        | Record<string, unknown>
        | undefined;
      const raw = (payload?.[key] ?? (payload as any)?.value) as unknown;
      if (typeof raw === "string") {
        this.cache.set(key, { value: raw, expiresAt: Date.now() + this.ttlMs });
        return raw;
      }
      return fallback;
    } catch {
      return fallback;
    }
  }

  /** Invalidate the entire cache (called when the host pushes a config change). */
  invalidate(): void {
    this.cache.clear();
  }
}
