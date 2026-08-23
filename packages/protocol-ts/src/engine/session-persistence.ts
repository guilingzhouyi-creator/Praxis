/**
 * SessionPersistence — language-neutral persistence interface (P0.6 mirror).
 *
 * Mirrors the Python3 DurableJsonStore contract: schema-versioned envelope,
 * checksum verification, atomic replace, and corruption fail-closed.
 *
 * TS implementations should use:
 *   - IndexedDB (browser) — transactional, async
 *   - node:fs + crypto (Node.js/WSL) — file-based with fsync
 *
 * TS pattern: abstract interface + generic `satisfies` constraint on
 * concrete implementations. The interface is the TS-mirrorable contract;
 * the Python3 side uses DurableJsonStore with the same envelope shape.
 */

import type { JsonObject } from "../records.ts";

/** Envelope format: {v, kind, checksum, payload} — mirrors DurableJsonStore. */
export interface StoreEnvelope<T = JsonObject> {
  v: number;
  kind: string;
  checksum: string;
  payload: T;
}

/** What a session snapshot looks like when persisted. */
export interface SessionSnapshot {
  session_id: string;
  title: string;
  status: "active" | "closed";
  turn_count: number;
  card_count: number;
  user_id: string;
  memory_scope: string;
  cell_id: string;
  role: string;
  model_config: Record<string, unknown>;
}

/**
 * Language-neutral persistence contract. Implementations must guarantee:
 *   - atomic write (no partial state visible to concurrent readers)
 *   - checksum verification on read (corruption detection)
 *   - fail-closed on unrecoverable damage (throw, never return garbage)
 */
export interface ISessionPersistence {
  /** Persist one session snapshot atomically; overwrites existing. */
  save(snapshot: SessionSnapshot): Promise<void>;
  /** Load a snapshot by session_id; returns undefined if absent. */
  load(sessionId: string): Promise<SessionSnapshot | undefined>;
  /** List all persisted session ids. */
  list(): Promise<string[]>;
  /** Remove a snapshot (called after close+archive). */
  remove(sessionId: string): Promise<void>;
}
