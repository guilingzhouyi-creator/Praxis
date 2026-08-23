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

export class ConfigReader {
  private cache = new Map<string, CacheEntry>();
  private readonly ttlMs: number;

  constructor(
    private readonly bridge: ProtocolBridge,
    { ttlMs = 30_000 }: ConfigReaderOptions = {},
  ) {
    this.ttlMs = ttlMs;
  }

  /** Read a string config value with TTL cache. */
  async getString(key: string, fallback = ""): Promise<string> {
    const cached = this.cache.get(key);
    if (cached && Date.now() < cached.expiresAt) return String(cached.value);
    try {
      const messages = await this.bridge.settingsGet(key);
      const payload = messages[0]?.payload as Record<string, unknown> | undefined;
      const raw = payload?.[key];
      const str = typeof raw === "string" ? raw : fallback;
      this.cache.set(key, { value: str, expiresAt: Date.now() + this.ttlMs });
      return str;
    } catch {
      return fallback;
    }
  }

  /** Invalidate the entire cache (called when the host pushes a config change). */
  invalidate(): void {
    this.cache.clear();
  }
}
