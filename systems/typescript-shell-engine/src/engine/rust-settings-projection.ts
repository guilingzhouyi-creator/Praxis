/**
 * Read-only projection of a Rust-owned settings snapshot.
 *
 * The Rust runtime remains the settings authority. This module only validates
 * the versioned value shape received from a bridge and exposes safe local
 * reads; it never writes settings or imports the Python runtime.
 */

export const MAX_SETTING_KEY_BYTES = 256;
export const MAX_SETTINGS = 512;

export type RustSettingsSource = "fallback" | "injected";

export interface RustSettingsSnapshot {
  revision: number;
  source: RustSettingsSource;
  values: Readonly<Record<string, unknown>>;
}

/** Parse the result payload emitted by Rust `settings_get`/`settings_set`. */
export function parseRustSettingsReply(input: unknown): RustSettingsSnapshot | null {
  if (!isRecord(input) || input.success !== true) return null;
  if (input.operation !== "settings_get" && input.operation !== "settings_set") return null;
  return parseRustSettingsSnapshot(input);
}

/** Parse and validate one Rust settings payload. */
export function parseRustSettingsSnapshot(input: unknown): RustSettingsSnapshot | null {
  if (!isRecord(input)) return null;
  const { revision, source, values } = input;
  if (
    typeof revision !== "number" ||
    !Number.isSafeInteger(revision) ||
    revision < 0 ||
    (source !== "fallback" && source !== "injected") ||
    !isRecord(values) ||
    Object.keys(values).length > MAX_SETTINGS
  ) {
    return null;
  }
  for (const key of Object.keys(values)) {
    if (!key.trim() || key.includes("\0") || key.length > MAX_SETTING_KEY_BYTES) return null;
  }
  return {
    revision,
    source,
    values: { ...values },
  };
}

/** Return one projected value without mutating the snapshot. */
export function projectRustSetting<T>(
  snapshot: RustSettingsSnapshot | null,
  key: string,
  fallback: T,
): unknown | T {
  if (!snapshot || !key) return fallback;
  return Object.prototype.hasOwnProperty.call(snapshot.values, key)
    ? snapshot.values[key]
    : fallback;
}

/**
 * Bounded read model for frontend consumers.
 *
 * Updates from the same source must be monotonic. A source transition (for
 * example, fallback → injected after persistent boot) is accepted explicitly.
 */
export class RustSettingsProjection {
  private current: RustSettingsSnapshot | null = null;

  /** Apply one payload, returning false when validation or revision checks fail. */
  update(input: unknown): boolean {
    const next = parseRustSettingsSnapshot(input);
    if (!next) return false;
    if (
      this.current &&
      this.current.source === next.source &&
      next.revision < this.current.revision
    ) {
      return false;
    }
    this.current = next;
    return true;
  }

  /** Return the current defensive snapshot, if one has been accepted. */
  snapshot(): RustSettingsSnapshot | null {
    if (!this.current) return null;
    return {
      revision: this.current.revision,
      source: this.current.source,
      values: { ...this.current.values },
    };
  }

  /** Read one value from the current snapshot. */
  get<T>(key: string, fallback: T): unknown | T {
    return projectRustSetting(this.current, key, fallback);
  }

  /** Drop the local projection without affecting Rust-owned settings. */
  clear(): void {
    this.current = null;
  }
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null && !Array.isArray(input);
}
