/**
 * Public entry point for the independent TypeScript L3 agent runtime.
 *
 * L2 imports this surface as data-only ingress; concrete Rust adapters are
 * injected by the host and remain the sole authority for side effects.
 */

export * from "./contracts/agent-contracts.ts";
export * from "./ports/runtime-ports.ts";
export * from "./runtime/limits.ts";
export * from "./runtime/ts-agent-runtime.ts";
export * from "./adapters/l2-intent-adapter.ts";
export * from "./adapters/rust-protocol-execution-port.ts";
