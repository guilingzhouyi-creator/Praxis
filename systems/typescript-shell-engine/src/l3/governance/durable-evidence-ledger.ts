/**
 * Durable evidence adapter for the TypeScript L3 governance boundary.
 *
 * The ledger remains an append-only, bounded projection. Durability is
 * injected through a small document store so the L3 runtime does not acquire
 * an implicit filesystem or process authority. The file adapter below is an
 * atomic JSON snapshot host adapter; deployments may replace it with a
 * database, Rust-owned store, or transactional outbox.
 */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";
import {
  InMemoryEvidenceLedger,
  type EvidenceChain,
  type EvidenceInput,
  type EvidenceLedgerDocument,
  type EvidencePoint,
  type EvidencePort,
  type EvidenceQuery,
  type EvidenceVerification,
} from "./evidence-ledger.ts";
import type { AgentRuntimeEvent } from "../contracts/agent-contracts.ts";

/** Storage boundary for atomically loading and committing evidence documents. */
export interface DurableEvidenceStorage {
  load(): EvidenceLedgerDocument | null;
  commit(document: EvidenceLedgerDocument): void;
}

/** Process-local durable storage useful for restart and failure tests. */
export class MemoryEvidenceStorage implements DurableEvidenceStorage {
  private document: EvidenceLedgerDocument | null = null;

  /** Load a detached document snapshot. */
  load(): EvidenceLedgerDocument | null {
    return this.document ? cloneDocument(this.document) : null;
  }

  /** Replace the stored document with a detached snapshot. */
  commit(document: EvidenceLedgerDocument): void {
    this.document = cloneDocument(document);
  }
}

/** Atomic JSON snapshot storage for a host-controlled evidence path. */
export class JsonFileEvidenceStorage implements DurableEvidenceStorage {
  constructor(private readonly path: string) {
    if (!path || path.includes("\0")) throw new TypeError("evidence storage path must be non-empty and NUL-free");
  }

  /** Load a JSON document, returning null when the path is absent. */
  load(): EvidenceLedgerDocument | null {
    if (!existsSync(this.path)) return null;
    const parsed: unknown = JSON.parse(readFileSync(this.path, "utf8"));
    return parsed as EvidenceLedgerDocument;
  }

  /** Atomically replace the JSON snapshot through a same-directory temporary file. */
  commit(document: EvidenceLedgerDocument): void {
    mkdirSync(dirname(this.path), { recursive: true });
    const temporary = `${this.path}.tmp-${process.pid}-${++temporarySequence}`;
    try {
      writeFileSync(temporary, JSON.stringify(document), { encoding: "utf8" });
      renameSync(temporary, this.path);
    } finally {
      try {
        if (existsSync(temporary)) unlinkSync(temporary);
      } catch {
        // The durable path itself remains the authoritative failure signal.
      }
    }
  }
}

let temporarySequence = 0;

function cloneDocument(document: EvidenceLedgerDocument): EvidenceLedgerDocument {
  return {
    ...document,
    points: document.points.map((point) => ({
      ...point,
      tags: { ...point.tags },
      raw: structuredClone(point.raw),
    })),
    chains: document.chains.map((chain) => ({ ...chain })),
  };
}

/** Durable wrapper that commits every state transition transactionally. */
export class DurableEvidenceLedger implements EvidencePort {
  private readonly memory: InMemoryEvidenceLedger;
  private readonly storage: DurableEvidenceStorage;

  constructor(options: {
    readonly storage: DurableEvidenceStorage;
    readonly ledger?: InMemoryEvidenceLedger;
    readonly ledgerOptions?: ConstructorParameters<typeof InMemoryEvidenceLedger>[0];
  }) {
    if (!options?.storage) throw new TypeError("durable evidence storage is required");
    this.storage = options.storage;
    this.memory = options.ledger ?? new InMemoryEvidenceLedger(options.ledgerOptions);
    const loaded = this.storage.load();
    if (loaded) this.memory.importDocument(loaded);
  }

  /** Begin or reuse a chain and persist the updated metadata. */
  beginChain(kind: string, source = ""): string {
    return this.transaction(() => this.memory.beginChain(kind, source));
  }

  /** Record one evidence point and persist the committed document. */
  record(input: EvidenceInput): string {
    return this.transaction(() => this.memory.record(input));
  }

  /** Close one chain and persist the updated metadata when it exists. */
  closeChain(chainId: string, reason = ""): EvidenceChain | null {
    const before = this.memory.exportDocument();
    const result = this.memory.closeChain(chainId, reason);
    if (!result) return null;
    try {
      this.storage.commit(this.memory.exportDocument());
      return result;
    } catch (error) {
      this.memory.importDocument(before);
      throw error;
    }
  }

  /** Return detached newest-first evidence points. */
  query(filter?: EvidenceQuery): readonly EvidencePoint[] {
    return this.memory.query(filter);
  }

  /** Return detached newest-first chain summaries. */
  chains(limit?: number): readonly EvidenceChain[] {
    return this.memory.chains(limit);
  }

  /** Verify the retained hash chain. */
  verify(): EvidenceVerification {
    return this.memory.verify();
  }

  /** Observe selected runtime metadata through the durable ledger. */
  recordRuntimeEvent(event: AgentRuntimeEvent): string | null {
    return this.transaction(() => this.memory.recordRuntimeEvent(event));
  }

  /** Return durable ledger diagnostics. */
  snapshot(): ReturnType<InMemoryEvidenceLedger["snapshot"]> {
    return this.memory.snapshot();
  }

  private transaction<T>(operation: () => T): T {
    const before = this.memory.exportDocument();
    try {
      const result = operation();
      this.storage.commit(this.memory.exportDocument());
      return result;
    } catch (error) {
      this.memory.importDocument(before);
      throw error;
    }
  }
}
