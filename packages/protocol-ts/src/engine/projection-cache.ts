/** Simple memoisation for expensive projections (keyed by string). */
const registry = new Map<string, unknown>();

/** Get cached or compute and cache. */
export function getCached<T extends object, R>(
  key: string,
  _source: T,
  compute: (source: T) => R,
): R {
  if (registry.has(key)) return registry.get(key) as R;
  const value = compute(_source);
  registry.set(key, value);
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
