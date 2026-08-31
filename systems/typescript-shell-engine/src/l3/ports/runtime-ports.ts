/**
 * Port aliases for the TypeScript L3 runtime.
 *
 * Keeping ports in a separate namespace prevents the runtime from importing
 * a concrete provider, process API, terminal implementation, or L2 transport.
 */

export type {
  AgentDecisionContext,
  AgentDecisionPort,
  AgentEventSink,
  KernelExecutionRequest,
  RustExecutionReceipt,
  RustKernelExecutionPort,
} from "../contracts/agent-contracts.ts";

export type { AgentContextProjection, ReadOnlyContextPort } from "../context/context-projection.ts";
export type { L3CoordinationPorts } from "./coordination-ports.ts";
