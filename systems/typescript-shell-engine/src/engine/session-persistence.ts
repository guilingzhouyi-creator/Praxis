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

import type { JsonObject } from "../wire-records.ts";

/** Envelope format: {v, kind, checksum, payload} — mirrors DurableJsonStore. */
export interface StoreEnvelope<T = JsonObject> {
  v: number;
  kind: string;
  checksum: string;
  payload: T;
}

/** In-memory fallback for tests and non-persistent environments. */
export class InMemorySessionPersistence implements ISessionPersistence {
  private store = new Map<string, SessionSnapshot>();

  async save(snapshot: SessionSnapshot): Promise<void> {
    this.store.set(snapshot.session_id, { ...snapshot });
  }

  async load(sessionId: string): Promise<SessionSnapshot | undefined> {
    const found = this.store.get(sessionId);
    return found ? { ...found } : undefined;
  }

  async list(): Promise<string[]> {
    return [...this.store.keys()];
  }

  async remove(sessionId: string): Promise<void> {
    this.store.delete(sessionId);
  }

  /** Wrap a snapshot in a StoreEnvelope with a trivial checksum (tests). */
  static envelopeOf(snapshot: SessionSnapshot): StoreEnvelope<SessionSnapshot> {
    const payload = JSON.stringify(snapshot);
    let hash = 0;
    for (let i = 0; i < payload.length; i++) hash = (hash * 31 + payload.charCodeAt(i)) >>> 0;
    return { v: 1, kind: "session_snapshot", checksum: hash.toString(16), payload: snapshot };
  }
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
