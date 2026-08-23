/**
 * ProjectionCache — GC-friendly memoisation of expensive projection results.
 *
 * Uses `WeakRef` so cached entries do not prevent GC of their keys; stale
 * entries are evicted lazily on next `getCached` (no `FinalizationRegistry`
 * retained to keep the runtime portable). This avoids leaks in long-lived
 * sessions where projections are recomputed for changing inputs.
 */

interface CacheEntry {
  ref: WeakRef<object>;
  value: unknown;
}

const registry = new Map<string, CacheEntry>();

/** Get a cached projection result, or compute and cache a new one. */
export function getCached<T extends object, R>(
  key: string,
  source: T,
  compute: (source: T) => R,
): R {
  const entry = registry.get(key);
  if (entry) {
    const obj = entry.ref.deref();
    if (obj === source) return entry.value as R;
    // Source object was GC'd or replaced — drop stale entry.
    registry.delete(key);
  }
  const value = compute(source);
  registry.set(key, { ref: new WeakRef(source), value });
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
