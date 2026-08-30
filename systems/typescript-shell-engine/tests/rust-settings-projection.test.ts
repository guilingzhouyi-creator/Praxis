import { describe, expect, it } from "vitest";
import {
  MAX_SETTINGS,
  RustSettingsProjection,
  parseRustSettingsReply,
  parseRustSettingsSnapshot,
  projectRustSetting,
} from "../src/engine/rust-settings-projection.ts";

describe("Rust settings projection", () => {
  it("accepts a bounded snapshot and exposes read-only values", () => {
    const snapshot = parseRustSettingsSnapshot({
      revision: 3,
      source: "injected",
      values: { "llm.provider": "rust-host", "prompt.inject.memory": true },
    });
    expect(snapshot).not.toBeNull();
    expect(projectRustSetting(snapshot, "llm.provider", "fallback")).toBe("rust-host");
    expect(projectRustSetting(snapshot, "missing", "fallback")).toBe("fallback");
  });

  it("rejects malformed revisions, sources, keys, and bounded counts", () => {
    expect(parseRustSettingsSnapshot({ revision: -1, source: "fallback", values: {} })).toBeNull();
    expect(parseRustSettingsSnapshot({ revision: 1, source: "python", values: {} })).toBeNull();
    expect(parseRustSettingsSnapshot({ revision: 1, source: "fallback", values: { "": true } })).toBeNull();
    expect(
      parseRustSettingsSnapshot({
        revision: 1,
        source: "fallback",
        values: { ["x".repeat(257)]: true },
      }),
    ).toBeNull();
    const values = Object.fromEntries(
      Array.from({ length: MAX_SETTINGS + 1 }, (_, index) => [`setting.${index}`, index]),
    );
    expect(parseRustSettingsSnapshot({ revision: 1, source: "fallback", values })).toBeNull();
  });

  it("rejects stale same-source updates but accepts source transitions", () => {
    const projection = new RustSettingsProjection();
    expect(projection.update({ revision: 4, source: "injected", values: { a: 4 } })).toBe(true);
    expect(projection.update({ revision: 3, source: "injected", values: { a: 3 } })).toBe(false);
    expect(projection.get("a", 0)).toBe(4);
    expect(projection.update({ revision: 0, source: "fallback", values: { a: 0 } })).toBe(true);
    expect(projection.get("a", 9)).toBe(0);
    const copy = projection.snapshot();
    expect(copy).not.toBeNull();
    expect(copy?.values).toEqual({ a: 0 });
    projection.clear();
    expect(projection.snapshot()).toBeNull();
  });

  it("accepts Rust command replies while rejecting failed or unknown operations", () => {
    const reply = parseRustSettingsReply({
      success: true,
      operation: "settings_get",
      revision: 7,
      source: "injected",
      key: "llm.model",
      value: "rust-model",
      values: { "llm.model": "rust-model" },
    });
    expect(reply?.values["llm.model"]).toBe("rust-model");
    expect(
      parseRustSettingsReply({
        success: false,
        operation: "settings_get",
        revision: 7,
        source: "injected",
        values: {},
      }),
    ).toBeNull();
    expect(
      parseRustSettingsReply({
        success: true,
        operation: "settings_reset",
        revision: 7,
        source: "injected",
        values: {},
      }),
    ).toBeNull();
  });
});
