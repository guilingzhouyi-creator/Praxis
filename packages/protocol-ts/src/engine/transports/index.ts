/**
 * Transport adapters for the protocol bridge.
 *
 * Each adapter implements the async line Transport contract
 * (`(line: string) => Promise<string[]>`): send one encoded JSONL envelope,
 * resolve with the host's response lines — built on the shared
 * line-transport engine (ack boundary, line/time budgets, no interleave).
 * stdio / http / ws / ssh all follow §2.6; add future transports here too.
 */

export { createLineRequestTransport, isAckLine } from "./line-transport.ts";
export { createStdioTransport } from "./stdio.ts";
export { createHttpTransport } from "./http.ts";
export { createWsTransport } from "./ws.ts";
export { createSshTransport } from "./ssh.ts";
export type { Transport } from "../bridge.ts";
