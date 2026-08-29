import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";
import { canonicalJson } from "../src/protocol/wire-records.ts";
import {
  ExecutionCheckpointError,
  RustExecutionStoreReader,
  decodeExecutionStoreDocument,
  encodeExecutionStoreDocument,
  validateExecutionStoreDocument,
} from "../src/engine/execution-checkpoint.ts";
import type { RustExecutionStoreDocument } from "../src/engine/execution-checkpoint.ts";

const fixturePath = new URL("../../../tests/fixtures/kernel_execution_store_document.json", import.meta.url);

async function fixture(): Promise<{ raw: string; document: RustExecutionStoreDocument }> {
  const raw = await readFile(fixturePath, "utf8");
  return { raw, document: decodeExecutionStoreDocument(raw) };
}

describe("Rust execution checkpoint reader", () => {
  it("decodes the shared Rust fixture and preserves canonical output", async () => {
    const { raw, document } = await fixture();
    expect(document.generation).toBe(3);
    expect(document.clean_shutdown).toBe(false);
    expect(document.sessions[0]?.snapshot.spec.session_id).toBe("session-golden");
    expect(document.terminals[0]?.terminal_id).toBe("terminal-golden");
    expect(document.loops[0]?.state).toBe("failed");
    expect(encodeExecutionStoreDocument(document)).toBe(canonicalJson(JSON.parse(raw)));
  });

  it("rejects unsafe counters, missing references, and invalid clean claims", async () => {
    const { document } = await fixture();
    expect(() => validateExecutionStoreDocument({ ...document, generation: Number.MAX_SAFE_INTEGER + 1 })).toThrow(
      ExecutionCheckpointError,
    );
    const missingSession = structuredClone(document);
    missingSession.terminals[0]!.session_id = "missing";
    expect(() => validateExecutionStoreDocument(missingSession)).toThrow(/missing session/);
    const badClean = structuredClone(document);
    badClean.clean_shutdown = true;
    expect(() => validateExecutionStoreDocument(badClean)).toThrow(/clean document/);
    const badLoop = structuredClone(document);
    badLoop.loops[0]!.spec.terminal_id = "missing-terminal";
    expect(() => validateExecutionStoreDocument(badLoop)).toThrow(/missing terminal/);
  });

  it("opens absent roots as fresh and refreshes only from disk", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "praxis-ts-execution-reader-"));
    try {
      const reader = await RustExecutionStoreReader.open(root);
      expect(reader.document().generation).toBe(0);
      const { raw, document } = await fixture();
      await mkdirCheckpoint(reader.checkpointFile(), raw);
      expect((await reader.refresh()).generation).toBe(document.generation);
      const snapshot = reader.document();
      snapshot.terminals.length = 0;
      expect(reader.document().terminals).toHaveLength(1);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

async function mkdirCheckpoint(checkpointPath: string, contents: string): Promise<void> {
  await mkdir(path.dirname(checkpointPath), { recursive: true });
  await writeFile(checkpointPath, contents, "utf8");
}
