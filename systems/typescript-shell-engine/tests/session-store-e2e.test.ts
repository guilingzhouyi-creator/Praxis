/** Cross-process Rust/TypeScript session-store contract tests.
 *
 * The suite is enabled only when the candidate probe has been built. It
 * verifies both directions at the process boundary; the normal TS suite does
 * not silently substitute an in-process fake when the probe is unavailable.
 */

import { execFile as nodeExecFile } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";

import { describe, expect, it } from "vitest";
import {
  RustSessionStore,
  decodeSessionStoreDocument,
} from "../src/engine/session-checkpoint.ts";

const execFile = promisify(nodeExecFile);
const probe = process.env.PRAXIS_RUST_SESSION_STORE_PROBE
  ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../systems/rust-kernel-engine/target/debug/rust-session-store-probe");
const processSuite = existsSync(probe) ? describe : describe.skip;

async function runProbe(command: "emit" | "validate", root: string): Promise<string> {
  const result = await execFile(probe, [command, root], { encoding: "utf8" });
  return result.stdout.trim();
}

processSuite("cross-process Rust session-store contract", () => {
  it("reads a checkpoint emitted by an independent Rust process", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "praxis-rust-session-e2e-"));
    try {
      const output = JSON.parse(await runProbe("emit", root)) as Record<string, unknown>;
      const store = await RustSessionStore.open(root);
      const document = store.document();
      expect(document).toMatchObject(output);
      expect(document.generation).toBe(1);
      expect(document.sessions[0]?.snapshot.spec.session_id).toBe("session-probe");
      expect(document.sessions[0]?.snapshot.state).toBe("crashed");
      expect(document.sessions[0]?.snapshot.messages[0]?.content).toBe("process-boundary");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  }, 30_000);

  it("lets Rust validate a checkpoint emitted by the TypeScript adapter", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "praxis-ts-rust-session-e2e-"));
    try {
      const store = await RustSessionStore.open(root);
      const fixturePath = new URL("../../../tests/fixtures/kernel_session_store_document.json", import.meta.url);
      const document = decodeSessionStoreDocument(await readFile(fixturePath, "utf8"));
      await store.save({ ...document, generation: 1 });
      const output = JSON.parse(await runProbe("validate", root)) as Record<string, unknown>;
      expect(output).toEqual(store.document());

      await writeFile(
        store.checkpointFile(),
        JSON.stringify({ ...document, generation: 1, store_version: 99 }),
        "utf8",
      );
      await expect(runProbe("validate", root)).rejects.toMatchObject({ code: 1 });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  }, 30_000);
});
