import { describe, expect, it } from "vitest";
import {
  AgentRuntime,
  AgentRuntimeError,
  projectToolRegistry,
  toolInvocationToKernelRequest,
  toolResultFromReceipt,
  type AgentIdentity,
  type AgentInput,
  type RustExecutionReceipt,
  type ToolInvocationRequest,
  type ToolSpecProjection,
} from "../src/l3/l3-agent-entry.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
};

const tool: ToolSpecProjection = {
  name: "read_file",
  description: "Read a bounded file",
  category: "files",
  ring: "RING_1",
  danger: 0,
  gates: ["G1", "G2"],
  parameters: [{ name: "path", type: "string", required: true, description: "Path" }],
  returns: { type: "object", description: "", properties: { success: "bool" } },
  parallelSafe: true,
  sandboxProfile: null,
};

function input(inputId = "session-1:1"): AgentInput {
  return {
    inputId,
    inputSeq: 1,
    text: "read a file",
    traceId: "trace-1",
    identity,
  };
}

function invocation(): ToolInvocationRequest {
  return {
    callId: "call-1",
    toolName: "read_file",
    args: { path: "README.md" },
    identity,
    traceId: "trace-1",
  };
}

describe("TypeScript L3 tool projection", () => {
  it("projects Python-style registry data deterministically without handlers", () => {
    const projected = projectToolRegistry({
      write_file: {
        name: "write_file",
        description: "Write a file",
        category: "files",
        ring: "RING_2_5",
        danger: 1,
        gates: ["G1", "G2", "G3"],
        parameters: [],
        parallel_safe: false,
        handler: "systems.python_reference.handler",
      },
      read_file: {
        ...tool,
        handler: "systems.python_reference.handler",
      },
    });

    expect(projected.map((entry) => entry.name)).toEqual(["read_file", "write_file"]);
    expect(projected[0]).toEqual(tool);
    expect("handler" in projected[0]!).toBe(false);
    expect(projected[1]?.ring).toBe("RING_2_5");
  });

  it("rejects duplicate or over-sized registry projections", () => {
    expect(() => projectToolRegistry([tool, tool])).toThrowError(AgentRuntimeError);
    expect(() => projectToolRegistry([tool], { maxTools: 0 })).toThrowError(AgentRuntimeError);
  });

  it("uses registered ring and danger metadata when creating a Rust tool request", () => {
    const request = toolInvocationToKernelRequest(invocation(), tool);

    expect(request).toMatchObject({
      requestId: "call-1",
      authority: "rust",
      operation: "tool.invoke",
      ring: 1,
      danger: 0,
      args: { tool_name: "read_file", arguments: { path: "README.md" } },
    });
  });

  it("folds a Rust receipt into a bounded data-only tool result", () => {
    const receipt: RustExecutionReceipt = {
      receiptId: "receipt-1",
      requestId: "call-1",
      accepted: true,
      status: "completed",
      traceId: "trace-1",
      data: { content: "hello" },
    };

    expect(toolResultFromReceipt(receipt, invocation())).toEqual({
      callId: "call-1",
      toolName: "read_file",
      receiptId: "receipt-1",
      traceId: "trace-1",
      success: true,
      status: "completed",
      data: { content: "hello" },
      error: undefined,
    });
  });

  it("routes a provider tool call through Rust and exposes the folded result", async () => {
    const requests: unknown[] = [];
    const events: string[] = [];
    const runtime = new AgentRuntime({
      tools: [tool],
      decision: {
        async decide() {
          return {
            decisionId: "decision-tool",
            actions: [{ kind: "tool_call", actionId: "call-1", toolName: "read_file", args: { path: "README.md" } }],
          };
        },
      },
      execution: {
        authority: "rust",
        async submit(request) {
          requests.push(request);
          return {
            receiptId: "receipt-1",
            requestId: request.requestId,
            accepted: true,
            status: "completed",
            traceId: request.traceId,
            data: { content: "hello" },
          };
        },
      },
      events: {
        publish(event) {
          events.push(event.type);
        },
      },
    });

    const result = await runtime.run(input("session-1:2"));

    expect(result.toolResults).toHaveLength(1);
    expect(result.toolResults[0]).toMatchObject({ toolName: "read_file", success: true });
    expect(requests[0]).toMatchObject({
      operation: "tool.invoke",
      ring: 1,
      danger: 0,
      args: { tool_name: "read_file" },
    });
    expect(events).toContain("tool_call_submitted");
    expect(events).toContain("tool_result_completed");
  });
});
