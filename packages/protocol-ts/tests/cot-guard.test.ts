import { describe, it, expect } from "vitest";
import { sanitizePayload, containsCoT, ALLOWED_PAYLOAD_KEYS } from "../src/engine/cot-guard.ts";

describe("CoT privacy guard (P2.6)", () => {
  it("strips reasoning fields at top level", () => {
    const result = sanitizePayload({ output: "answer", reasoning: "secret" });
    expect(result).toEqual({ output: "answer" });
    expect("reasoning" in result).toBe(false);
  });

  it("strips nested reasoning fields", () => {
    const result = sanitizePayload({ data: { thinking: "...", ok: true } });
    const inner = result.data as Record<string, unknown>;
    expect("thinking" in inner).toBe(false);
    expect(inner.ok).toBe(true);
  });

  it("preserves arrays while sanitizing elements", () => {
    const result = sanitizePayload({ items: [{ reasoning: "r", value: 1 }, { safe: true }] });
    const arr = result.items as Array<Record<string, unknown>>;
    expect(arr[0].value).toBe(1);
    expect("reasoning" in arr[0]).toBe(false);
  });
});

describe("containsCoT detection", () => {
  it("detects top-level reasoning key", () => {
    expect(containsCoT({ reasoning: "x" })).toBe(true);
  });
  it("detects nested reasoning_content key", () => {
    expect(containsCoT({ deep: { reasoning_content: "leak" } })).toBe(true);
  });
  it("returns false for clean payloads", () => {
    expect(containsCoT({ success: true, output: "clean" })).toBe(false);
  });
});

describe("ALLOWED_PAYLOAD_KEYS contract", () => {
  it("covers all message kinds", () => {
    const kinds = Object.keys(ALLOWED_PAYLOAD_KEYS).sort();
    expect(kinds).toEqual(["ack","command","control","event","intent","result","stream_chunk"].sort());
  });
});
