import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";
import {
  RustSessionStore,
  SessionCheckpointError,
  decodeSessionStoreDocument,
  encodeSessionStoreDocument,
  validateSessionStoreDocument,
} from "../src/engine/session-checkpoint.ts";
import { canonicalJson } from "../src/wire-records.ts";
import type { RustSessionStoreDocument } from "../src/engine/session-checkpoint.ts";

const fixturePath = new URL("../../../tests/fixtures/kernel_session_store_document.json", import.meta.url);

async function fixture(): Promise<{ raw: string; document: RustSessionStoreDocument }> {
  const raw = await readFile(fixturePath, "utf8");
  return { raw, document: decodeSessionStoreDocument(raw) };
}

describe("Rust session-store codec", () => {
  it("decodes the shared Rust fixture and re-encodes canonically", async () => {
    const { raw, document } = await fixture();
    expect(document.sessions[0]?.snapshot.spec.session_id).toBe("session-golden");
    expect(encodeSessionStoreDocument(document)).toBe(canonicalJson(JSON.parse(raw)));
    expect(document.sessions[0]?.snapshot.state).toBe("crashed");
  });

  it("rejects unsafe counters and invalid clean-shutdown claims", async () => {
    const { document } = await fixture();
    expect(() => validateSessionStoreDocument({ ...document, generation: Number.MAX_SAFE_INTEGER + 1 })).toThrow(
      SessionCheckpointError,
    );
    const bad = structuredClone(document);
    bad.clean_shutdown = true;
    expect(() => validateSessionStoreDocument(bad)).toThrow(/clean document/);
    const oversized = structuredClone(document);
    oversized.sessions[0]!.snapshot.spec.max_messages = 16_385;
    expect(() => validateSessionStoreDocument(oversized)).toThrow(/max_messages/);
  });

  it("writes an atomic checkpoint file and reopens it", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "praxis-ts-session-store-"));
    try {
      const store = await RustSessionStore.open(root);
      const { document } = await fixture();
      const first = { ...document, generation: 1 };
      await store.save(first);
      expect(JSON.parse(await readFile(store.checkpointFile(), "utf8"))).toEqual(first);
      const reopened = await RustSessionStore.open(root);
      expect(reopened.document()).toEqual(first);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("serializes concurrent writes behind the generation boundary", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "praxis-ts-session-store-"));
    try {
      const store = await RustSessionStore.open(root);
      const { document } = await fixture();
      const first = { ...document, generation: 1 };
      const second = { ...document, generation: 2 };
      await Promise.all([store.save(first), store.save(second)]);
      expect(store.document().generation).toBe(2);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
