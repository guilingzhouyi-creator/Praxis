import { describe, expect, it } from "vitest";
import {
  AgentRuntime,
  AgentRuntimeError,
  copyContextProjection,
  type AgentContextProjection,
  type AgentIdentity,
  type AgentInput,
} from "../src/l3/l3-agent-entry.ts";

const identity: AgentIdentity = {
  agentId: "agent-1",
  cellId: "cell-1",
  sessionId: "session-1",
  terminalId: "terminal-1",
};

function input(inputId = "session-1:1"): AgentInput {
  return {
    inputId,
    inputSeq: 1,
    text: "inspect context",
    traceId: "trace-context",
    identity,
  };
}

function context(overrides: Partial<AgentContextProjection> = {}): AgentContextProjection {
  return {
    identity,
    refs: [{
      refId: "memory:1",
      source: "memory",
      digest: "sha256:abc",
      bytes: 12,
      metadata: { tier: "R2" },
    }],
    totalBytes: 12,
    truncated: false,
    ...overrides,
  };
}

describe("TypeScript L3 read-only context projection", () => {
  it("copies identity-scoped digest refs without source content", () => {
    const original = context();
    const detached = copyContextProjection(original, identity);

    expect(detached).toEqual(original);
    expect(detached).not.toBe(original);
    expect(detached.identity).not.toBe(identity);
    expect(detached.refs).not.toBe(original.refs);
    expect(detached.refs[0]?.metadata).not.toBe(original.refs[0]?.metadata);
    expect("content" in detached.refs[0]!).toBe(false);
  });

  it("rejects foreign identities, duplicate refs, and byte-budget overflow", () => {
    expect(() => copyContextProjection(context({
      identity: { ...identity, sessionId: "foreign" },
    }), identity)).toThrowError(AgentRuntimeError);
    expect(() => copyContextProjection(context({
      refs: [context().refs[0]!, context().refs[0]!],
      totalBytes: 24,
    }), identity)).toThrowError(AgentRuntimeError);
    expect(() => copyContextProjection(context({
      refs: [{ ...context().refs[0]!, bytes: 100 }],
      totalBytes: 100,
    }), identity, { maxBytes: 64 })).toThrowError(AgentRuntimeError);
  });

  it("loads context before provider admission and passes a detached projection", async () => {
    let loadedIdentity: AgentIdentity | undefined;
    let providerContext: AgentContextProjection | undefined;
    const runtime = new AgentRuntime({
      context: {
        async load(requestIdentity) {
          loadedIdentity = requestIdentity;
          return context();
        },
      },
      decision: {
        async decide(_input, decisionContext) {
          providerContext = decisionContext.context;
          return { decisionId: "context-decision", actions: [] };
        },
      },
      execution: { authority: "rust", async submit() {
        throw new Error("execution should not be called");
      } },
    });

    await runtime.run(input());

    expect(loadedIdentity).toEqual(identity);
    expect(providerContext).toMatchObject({
      identity,
      refs: [{ refId: "memory:1", source: "memory", bytes: 12 }],
      totalBytes: 12,
    });
    expect(providerContext).not.toBe(context());
  });
});
