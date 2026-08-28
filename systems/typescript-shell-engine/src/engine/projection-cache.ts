/** Bounded memoisation for expensive projections (keyed by string). */

/** Maximum cached projections (FIFO eviction beyond this). */
export const PROJECTION_CACHE_CAPACITY = 256 as const;

const registry = new Map<string, unknown>();

/** Get cached or compute and cache; FIFO-evicts the oldest at capacity. */
export function getCached<T extends object, R>(
  key: string,
  _source: T,
  compute: (source: T) => R,
): R {
  const hit = registry.get(key);
  if (hit !== undefined) return hit as R;
  const value = compute(_source);
  registry.set(key, value);
  if (registry.size > PROJECTION_CACHE_CAPACITY) {
    // Map preserves insertion order; FIFO-evict the oldest key.
    const oldest = registry.keys().next().value;
    if (oldest !== undefined) registry.delete(oldest);
  }
  return value;
}

/** Explicitly evict one key (called when the underlying data changes). */
export function invalidate(key: string): void {
  registry.delete(key);
}

/** Clear the entire projection cache (tests / lifecycle reset). */
export function clearProjectionCache(): void {
  registry.clear();
}

/** Current cache size (diagnostics / tests). */
export function projectionCacheSize(): number {
  return registry.size;
}
