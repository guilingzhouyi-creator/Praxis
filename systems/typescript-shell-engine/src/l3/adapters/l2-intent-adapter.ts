/**
 * Adapter from the L2 protocol envelope to the L3 agent input contract.
 *
 * The adapter copies only the normalized intent fields needed by L3. It does
 * not dispatch commands, invoke tools, or infer Rust authorization.
 */

import type { Message } from "../../protocol/wire-envelope.ts";
import {
  AgentRuntimeError,
  type AgentIdentity,
  type AgentInput,
} from "../contracts/agent-contracts.ts";

/** Convert one validated L2 intent envelope into an L3 input value. */
export function intentFromL2(message: Message, identity: AgentIdentity): AgentInput {
  if (message.kind !== "intent") {
    throw new AgentRuntimeError("invalid_input", `L3 ingress requires an intent message, got ${message.kind}`);
  }
  if (message.session_id !== identity.sessionId) {
    throw new AgentRuntimeError("invalid_input", "L2 intent session does not match the Agent identity");
  }
  const text = message.payload.text;
  if (typeof text !== "string" || text.length === 0) {
    throw new AgentRuntimeError("invalid_input", "L2 intent text must be non-empty");
  }
  return {
    inputId: `${message.session_id}:${message.seq}`,
    inputSeq: message.seq,
    text,
    traceId: message.trace_id ?? "",
    identity: { ...identity },
  };
}
