/**
 * L3 bridge interface — the typed contract between the TS engine and the
 * Python3 L3 host (reserved for future expansion per l3-module-map.md).
 *
 * This module declares ONLY the shape of commands the TS side may send.
 * It never re-implements domain logic. Each command maps to exactly one
 * Python3 handler; the return type is always `Message[]` from envelope.ts.
 *
 * Design constraint (from agent-os-3x-closure.md §5):
 *   "TS owns no scheduler, AgentLoop, tool execution, memory promotion,
 *    skill mutation, or workflow decision"
 */

import type { ProtocolBridge } from "./bridge.ts";
import type { Message } from "../envelope.ts";

/**
 * Domain-grouped command surface exposed to TS frontends.
 * Each method delegates to ProtocolBridge.command() and returns raw
 * Message[] responses — the TS side NEVER interprets domain semantics.
 */
export interface IL3Bridge {
  settings: {
    get(key?: string): Promise<Message[]>;
    set(key: string, value: unknown): Promise<Message[]>;
  };
  memory: {
    digest(): Promise<Message[]>;
  };
  system: {
    status(): Promise<Message[]>;
  };
  model: {
    specs(): Promise<Message[]>;
  };
  selector: {
    cellLiveness(): Promise<Message[]>;
  };
}

/** Factory: build an IL3Bridge from a ProtocolBridge instance. */
export function createL3Bridge(bridge: ProtocolBridge): IL3Bridge {
  return {
    settings: {
      get: (key = "") => bridge.settingsGet(key),
      set: (key, value) => bridge.settingsSet(key, value),
    },
    memory: {
      digest: () => bridge.memoryDigest(),
    },
    system: {
      status: () => bridge.systemStatus(),
    },
    model: {
      specs: () => bridge.modelSpecs(),
    },
    selector: {
      cellLiveness: () => bridge.cellLiveness(),
    },
  };
}
