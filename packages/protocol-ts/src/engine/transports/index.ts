/**
 * Transport adapters for the protocol bridge.
 *
 * Each adapter implements the async line Transport contract
 * (`(line: string) => Promise<string[]>`): send one encoded JSONL envelope,
 * resolve with the host's response lines. Add WS/SSH adapters here too.
 */

export { createStdioTransport } from "./stdio.ts";
export { createHttpTransport } from "./http.ts";
export type { Transport } from "../bridge.ts";
