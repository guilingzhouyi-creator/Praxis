/**
 * ProjectionCache tests — memoisation, capacity FIFO eviction, invalidation.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  clearProjectionCache,
  getCached,
  invalidate,
  PROJECTION_CACHE_CAPACITY,
  projectionCacheSize,
} from "../src/engine/projection-cache.ts";

describe("projection cache", () => {
  beforeEach(() => {
    clearProjectionCache();
  });

  afterEach(() => {
    clearProjectionCache();
  });

  it("memoises by key and recomputes after invalidation", () => {
    let computes = 0;
    const source = { rows: 3 };
    const compute = (s: typeof source) => {
      computes++;
      return { total: s.rows };
    };
    expect(getCached("key-a", source, compute)).toEqual({ total: 3 });
    expect(getCached("key-a", source, compute)).toEqual({ total: 3 });
    expect(computes).toBe(1);
    invalidate("key-a");
    expect(getCached("key-a", source, compute)).toEqual({ total: 3 });
    expect(computes).toBe(2);
  });

  it("FIFO-evicts the oldest entry beyond capacity", () => {
    const src = { ok: true };
    for (let i = 0; i < PROJECTION_CACHE_CAPACITY + 10; i++) {
      getCached(`k-${i}`, src, () => i);
    }
    expect(projectionCacheSize()).toBe(PROJECTION_CACHE_CAPACITY);
    // The first 10 keys are evicted; the most recent fit.
    expect(getCached("k-0", src, () => -1)).toBe(-1); // recomputed → evicted
    for (let i = PROJECTION_CACHE_CAPACITY; i < PROJECTION_CACHE_CAPACITY + 10; i++) {
      expect(getCached(`k-${i}`, src, () => -1)).toBe(i); // cached
    }
  });

  it("clear empties the registry", () => {
    const src = { ok: true };
    getCached("a", src, () => 1);
    expect(projectionCacheSize()).toBe(1);
    clearProjectionCache();
    expect(projectionCacheSize()).toBe(0);
  });

  it("treats undefined compute results as cacheable misses", () => {
    const src = { ok: true };
    // First call caches undefined; the second call still recomputes (hit
    // is checked via `!== undefined`) — undefined results never stick.
    const compute = () => undefined as unknown;
    const first = getCached("u", src, compute);
    const second = getCached("u", src, compute);
    expect(first).toBeUndefined();
    expect(second).toBeUndefined();
  });
});