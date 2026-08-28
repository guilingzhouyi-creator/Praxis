/**
 * CommandHistory tests — bounded record, search, time range, clear semantics.
 */

import { describe, expect, it } from "vitest";
import { CommandHistory } from "../src/engine/command-history.ts";

describe("CommandHistory", () => {
  it("records entries with monotonic seq and metadata", () => {
    const h = new CommandHistory<string>(20);
    const a = h.record("ls", "ls", "ok", 3);
    const b = h.record("status", "status");
    expect(a.seq).toBe(1);
    expect(b.seq).toBe(2);
    expect(b.input).toBe("status");
    expect(b.result).toBeUndefined();
  });

  it("bounds the history at maxSize (oldest dropped)", () => {
    const h = new CommandHistory<null>(3);
    h.record("a", "a");
    h.record("b", "b");
    h.record("c", "c");
    h.record("d", "d");
    expect(h.length).toBe(3);
    expect(h.bySeq(1)).toBeUndefined();
    expect(h.bySeq(4)?.input).toBe("d");
  });

  it("searches case-insensitively on input lines", () => {
    const h = new CommandHistory(10);
    h.record("Deploy --env prod", "deploy");
    h.record("status --json", "status");
    expect(h.search("deploy")).toHaveLength(1);
    expect(h.search("STATUS")).toHaveLength(1);
    expect(h.search("absent")).toHaveLength(0);
  });

  it("filters by time range", () => {
    const h = new CommandHistory(10);
    const early = h.record("a", "a");
    h.record("b", "b");
    const from = new Date(early.timestamp);
    const to = new Date(Date.now() + 1);
    expect(h.byTimeRange(from, to)).toHaveLength(2);
    expect(h.byTimeRange(new Date(to.getTime() + 1000), new Date(to.getTime() + 2000))).toHaveLength(0);
  });

  it("recent returns newest-first up to n", () => {
    const h = new CommandHistory(10);
    for (let i = 1; i <= 5; i++) h.record(`c${i}`, `c${i}`);
    const recent = h.recent(2).map((e) => e.input);
    expect(recent).toEqual(["c5", "c4"]);
  });

  it("clear resets both entries and the seq counter", () => {
    const h = new CommandHistory(10);
    h.record("a", "a");
    h.record("b", "b");
    h.clear();
    expect(h.length).toBe(0);
    expect(h.bySeq(1)).toBeUndefined();
    // A fresh cycle restarts numbering at 1 (no monotonic leak).
    const first = h.record("c", "c");
    expect(first.seq).toBe(1);
  });
});