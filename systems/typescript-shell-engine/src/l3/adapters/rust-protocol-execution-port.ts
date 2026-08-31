/**
 * Rust protocol adapter for the TypeScript L3 execution port.
 *
 * The adapter carries one L3 kernel request over the existing protocol-v1
 * command boundary. It does not infer authorization, create process handles,
 * or interpret terminal bytes: Rust remains responsible for registration,
 * GateChain/capability adjudication, and execution.
 */

import type { Message } from "../../protocol/wire-envelope.ts";
import type { JsonObject } from "../../protocol/wire-records.ts";
import type {
  KernelExecutionRequest,
  RustExecutionReceipt,
  RustKernelExecutionPort,
} from "../contracts/agent-contracts.ts";
import {
  AgentRuntimeError,
  copyJsonObject,
} from "../contracts/agent-contracts.ts";

/** Narrow command surface needed from ProtocolBridge or a test double. */
export interface RustCommandBridge {
  readonly sessionId: string;
  commandPayload(
    name: string,
    payload?: JsonObject,
    sessionId?: string,
    traceId?: string,
  ): Promise<Message[]>;
}

/** Build a Rust-backed L3 execution port over the protocol-v1 bridge. */
export function createRustProtocolExecutionPort(
  bridge: RustCommandBridge,
): RustKernelExecutionPort {
  return {
    authority: "rust",
    async submit(request: KernelExecutionRequest, signal?: AbortSignal): Promise<RustExecutionReceipt> {
      if (signal?.aborted) {
        throw new AgentRuntimeError("cancelled", "Rust execution request was cancelled");
      }
      if (bridge.sessionId !== request.identity.sessionId) {
        throw new AgentRuntimeError(
          "execution_failed",
          "Rust execution bridge session does not match the Agent identity",
        );
      }

      let args: string;
      try {
        args = JSON.stringify(request.args);
      } catch (error) {
        throw new AgentRuntimeError(
          "execution_failed",
          `Rust execution args could not be serialized: ${String(error)}`,
        );
      }

      const responses = await bridge.commandPayload(
        request.operation,
        {
          args: [args],
          danger: request.danger,
          request_id: request.requestId,
          ring: request.ring,
        },
        request.identity.sessionId,
        request.traceId,
      );
      if (signal?.aborted) {
        throw new AgentRuntimeError("cancelled", "Rust execution request was cancelled");
      }
      const result = responses.find((message) => message.kind === "result");
      if (!result) {
        throw new AgentRuntimeError(
          "invalid_receipt",
          "Rust execution response did not contain a result envelope",
        );
      }
      return receiptFromResult(result, request);
    },
  };
}

function receiptFromResult(
  result: Message,
  request: KernelExecutionRequest,
): RustExecutionReceipt {
  const payload = result.payload;
  if (typeof payload.success !== "boolean") {
    throw new AgentRuntimeError("invalid_receipt", "Rust result payload lacks a boolean success field");
  }
  const data: JsonObject = {};
  for (const [key, value] of Object.entries(payload)) {
    if (key !== "success" && key !== "error" && key !== "receipt_id" && key !== "request_id") {
      data[key] = value;
    }
  }
  const error = typeof payload.error === "string" ? payload.error : undefined;
  if (typeof payload.request_id === "string" && payload.request_id !== request.requestId) {
    throw new AgentRuntimeError("invalid_receipt", "Rust result request id does not match the submitted action");
  }
  return {
    receiptId: typeof payload.receipt_id === "string"
      ? payload.receipt_id
      : `${request.requestId}:${result.seq}`,
    requestId: request.requestId,
    accepted: payload.success,
    status: payload.success ? "completed" : "rejected",
    traceId: result.trace_id ?? "",
    data: Object.keys(data).length > 0 ? copyJsonObject(data) : undefined,
    error,
  };
}
