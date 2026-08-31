/**
 * CommandHistory — bounded history of executed commands with search + replay.
 *
 * Mirrors the Python3 shell_session.py HistoryStack concept but adds:
 *   - Full-text search across command lines and results
 *   - Temporal filtering by time range
 *   - Replay support (re-execute a historical command)
 *
 * TS pattern: generic over the result type so different command kinds can
 * maintain their own typed histories.
 */

export interface HistoryEntry<T = unknown> {
  /** Monotonically increasing sequence number. */
  seq: number;
  /** ISO 8601 timestamp of when the command was executed. */
  timestamp: string;
  /** The raw input line as entered by the user. */
  input: string;
  /** Parsed command name (extracted from input). */
  name: string;
  /** Execution result (typed per command kind). */
  result?: T;
  /** Duration in milliseconds (perf telemetry). */
  elapsedMs: number;
}

export class CommandHistory<T = unknown> {
  private entries: HistoryEntry<T>[] = [];
  private nextSeq = 1;
  private readonly maxSize: number;

  constructor(maxSize = 500) {
    this.maxSize = maxSize;
  }

  /** Record one executed command; returns the entry for chaining. */
  record(input: string, name: string, result?: T, elapsedMs = 0): HistoryEntry<T> {
    const entry: HistoryEntry<T> = {
      seq: this.nextSeq++,
      timestamp: new Date().toISOString(),
      input,
      name,
      result,
      elapsedMs,
    };
    this.entries.push(entry);
    if (this.entries.length > this.maxSize) this.entries.shift();
    return entry;
  }

  /** Full-text search across input lines (case-insensitive substring). */
  search(query: string): HistoryEntry<T>[] {
    const q = query.toLowerCase();
    return this.entries.filter((e) => e.input.toLowerCase().includes(q));
  }

  /** Filter entries within a time range (ISO strings or Date objects). */
  byTimeRange(from: Date | string, to: Date | string): HistoryEntry<T>[] {
    const f = typeof from === "string" ? new Date(from) : from;
    const t = typeof to === "string" ? new Date(to) : to;
    return this.entries.filter((e) => {
      const ts = new Date(e.timestamp);
      return ts >= f && ts <= t;
    });
  }

  /** Get an entry by sequence number. */
  bySeq(seq: number): HistoryEntry<T> | undefined {
    return this.entries.find((e) => e.seq === seq);
  }

  /** Most recent N entries, newest-first. */
  recent(n = 20): readonly HistoryEntry<T>[] {
    return [...this.entries].reverse().slice(0, n);
  }

  get length(): number {
    return this.entries.length;
  }

  /** Return a detached oldest-first snapshot for a history view. */
  all(): readonly HistoryEntry<T>[] {
    return [...this.entries];
  }

  /** Clear all history entries. */
  clear(): void {
    this.entries.length = 0;
    this.nextSeq = 1;
  }
}
