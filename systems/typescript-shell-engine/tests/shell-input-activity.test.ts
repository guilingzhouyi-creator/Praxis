import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  INPUT_ACTIVITY_CONTRACT_VERSION,
  aggregateInputActivity,
  validateInputActivityConfig,
  validateInputActivitySnapshot,
  type InputActivityObservation,
  type InputActivityProbeConfig,
  type InputActivitySnapshot,
} from "../src/terminal-input-telemetry.ts";

const fixturePath = fileURLToPath(
  new URL("../../../tests/fixtures/kernel_input_activity_vectors.json", import.meta.url),
);
const fixture = JSON.parse(readFileSync(fixturePath, "utf-8")) as {
  contract_version: number;
  config: InputActivityProbeConfig;
  cases: Array<{
    name: string;
    now: number;
    observations: InputActivityObservation[];
    expected: InputActivitySnapshot;
  }>;
};

describe("aggregate input activity projection", () => {
  it("matches the shared Rust vectors", () => {
    expect(fixture.contract_version).toBe(INPUT_ACTIVITY_CONTRACT_VERSION);
    for (const caseItem of fixture.cases) {
      expect(aggregateInputActivity(caseItem.now, caseItem.observations, fixture.config)).toEqual(
        caseItem.expected,
      );
    }
  });

  it("rejects duplicate, stale-contract, and unauthorized activity observations", () => {
    const active: InputActivityObservation = {
      source: "keyboard",
      permission: "granted",
      keyboard_active: true,
      pointer_active: false,
      last_activity_at: 10,
    };
    expect(() => aggregateInputActivity(10, [active, active], { idle_after_seconds: 5, max_sources: 4 })).toThrow();
    expect(() => aggregateInputActivity(
      10,
      [{ ...active, permission: "denied" }],
      { idle_after_seconds: 5, max_sources: 4 },
    )).toThrow();
    expect(() => aggregateInputActivity(
      10,
      [{ ...active, last_activity_at: 11 }],
      { idle_after_seconds: 5, max_sources: 4 },
    )).toThrow();
    expect(() => validateInputActivityConfig({ idle_after_seconds: 0, max_sources: 4 })).toThrow();
    expect(validateInputActivitySnapshot(fixture.cases[0].expected)).toEqual([]);
  });

  it("rejects runtime JSON values that violate the typed observation contract", () => {
    const valid: InputActivityObservation = {
      source: "keyboard",
      permission: "granted",
      keyboard_active: true,
      pointer_active: false,
      last_activity_at: 10,
    };
    expect(() => aggregateInputActivity(
      10,
      [{ ...valid, source: 42 } as unknown as InputActivityObservation],
    )).toThrow();
    expect(() => aggregateInputActivity(
      10,
      [{ ...valid, keyboard_active: "true" } as unknown as InputActivityObservation],
    )).toThrow();
    expect(() => aggregateInputActivity(
      10,
      [{ ...valid, last_activity_at: "10" } as unknown as InputActivityObservation],
    )).toThrow();
  });
});
