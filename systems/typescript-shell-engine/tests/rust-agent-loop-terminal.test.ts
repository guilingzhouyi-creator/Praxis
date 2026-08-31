import { describe, expect, it } from "vitest";
import {
  AGENT_LOOP_TERMINAL_MAX_BATCH,
  RustAgentLoopTerminalProjection,
  encodeRustTerminalFrame,
  parseRustAgentLoopTerminalBinding,
  parseRustTerminalFrame,
  parseRustTerminalFrameBatch,
} from "../src/engine/rust-agent-loop-terminal.ts";

const BINDING = {
  contract_version: 1,
  spec: {
    loop_id: "loop-1",
    agent_id: "agent-1",
    cell_id: "cell-1",
    session_id: "session-1",
    terminal_id: "terminal-1",
  },
  session_id: "session-1",
  terminal_state: "running",
} as const;

describe("Rust terminal-backed AgentLoop projection", () => {
  it("accepts a versioned binding and rejects mismatched identity/state", () => {
    expect(parseRustAgentLoopTerminalBinding(BINDING)?.spec.loop_id).toBe("loop-1");
    expect(
      parseRustAgentLoopTerminalBinding({
        ...BINDING,
        session_id: "other-session",
      }),
    ).toBeNull();
    expect(
      parseRustAgentLoopTerminalBinding({
        ...BINDING,
        terminal_state: "unknown",
      }),
    ).toBeNull();
    expect(
      parseRustAgentLoopTerminalBinding({
        ...BINDING,
        contract_version: 2,
      }),
    ).toBeNull();
  });

  it("round-trips bounded opaque bytes without decoding or aliasing", () => {
    const frame = parseRustTerminalFrame({
      sequence: 7,
      stream: "input",
      data: [0, 10, 255],
    });
    expect(frame).not.toBeNull();
    expect([...frame!.data]).toEqual([0, 10, 255]);
    const encoded = encodeRustTerminalFrame(frame!);
    expect(encoded).toEqual({ sequence: 7, stream: "input", data: [0, 10, 255] });
    frame!.data[0] = 99;
    expect(encoded?.data[0]).toBe(0);
    const source = new Uint8Array([4, 5]);
    const copied = parseRustTerminalFrame({ sequence: 8, stream: "input", data: source });
    source[0] = 99;
    expect([...copied!.data]).toEqual([4, 5]);
  });

  it("rejects invalid bytes, sequences, directions, and oversized batches", () => {
    expect(parseRustTerminalFrame({ sequence: 0, stream: "input", data: [] })).toBeNull();
    expect(parseRustTerminalFrame({ sequence: 1, stream: "input", data: [256] })).toBeNull();
    expect(parseRustTerminalFrame({ sequence: 1, stream: "input", data: "hello" })).toBeNull();
    expect(parseRustTerminalFrame({ sequence: 1, stream: "input", data: Array(2) })).toBeNull();
    expect(parseRustTerminalFrameBatch([,] as unknown[])).toBeNull();
    expect(parseRustTerminalFrameBatch([], undefined, 1.5)).toBeNull();
    expect(
      parseRustTerminalFrameBatch(
        Array.from({ length: AGENT_LOOP_TERMINAL_MAX_BATCH + 1 }, () => ({
          sequence: 1,
          stream: "input",
          data: [],
        })),
      ),
    ).toBeNull();
    expect(
      parseRustTerminalFrameBatch(
        [{ sequence: 1, stream: "output", data: [] }],
        "input",
      ),
    ).toBeNull();
  });

  it("projects one identity and keeps direction-specific frame views", () => {
    const projection = new RustAgentLoopTerminalProjection();
    expect(projection.inputFrame({ sequence: 1, stream: "input", data: [1] })).toBeNull();
    expect(projection.updateBinding(BINDING)).toBe(true);
    expect(
      projection.updateBinding({
        ...BINDING,
        spec: { ...BINDING.spec, terminal_id: "terminal-2" },
      }),
    ).toBe(false);
    expect(
      projection.updateBinding({
        ...BINDING,
        spec: { ...BINDING.spec, agent_id: "agent-2" },
      }),
    ).toBe(false);
    const input = projection.inputFrame({ sequence: 1, stream: "input", data: [1] });
    expect(input?.stream).toBe("input");
    expect(projection.inputFrame({ sequence: 2, stream: "output", data: [2] })).toBeNull();
    const output = projection.outputFrame({ sequence: 3, stream: "error", data: [3] });
    expect(output?.stream).toBe("error");
    output!.data[0] = 9;
    expect(projection.outputFrame({ sequence: 3, stream: "error", data: [3] })?.data[0]).toBe(3);
    const binding = projection.binding();
    expect(binding?.spec.terminal_id).toBe("terminal-1");
    projection.clear();
    expect(projection.binding()).toBeNull();
  });
});
