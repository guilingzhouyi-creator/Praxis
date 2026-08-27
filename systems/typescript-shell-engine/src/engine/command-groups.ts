/**
 * Command groups — dispatcher registrations mirroring Python command domains.
 *
 * Each group registers command names that route to the bridge (the host
 * stays the authority) using the domain-grouped bridge helpers. Local
 * handlers are pure rendering only; anything needing L3 state goes through
 * the bridge — the TS shell never re-implements the domain logic.
 */

import type { ProtocolBridge } from "./bridge.ts";
import type { Dispatcher } from "./dispatcher.ts";

export interface CommandGroupOptions {
  bridge: ProtocolBridge;
}

/**
 * Register the settings domain commands: read all/one, write one.
 * Write authority stays on the host (single write surface via the bridge).
 */
export function registerSettingsGroup(dispatcher: Dispatcher, { bridge }: CommandGroupOptions): void {
  dispatcher.register("settings", async (args) => {
    const key = args[0] ?? "";
    const messages = await bridge.settingsGet(key);
    return { kind: "local", data: { domain: "settings", key, messages } };
  });
  dispatcher.register("settings-set", async (args) => {
    if (args.length < 2) return { kind: "local", data: { success: false, error: "usage: settings-set <key> <value>" } };
    const messages = await bridge.settingsSet(args[0], args[1]);
    return { kind: "local", data: { domain: "settings", key: args[0], messages } };
  });
}

/** Register the system/status domain commands. */
export function registerSystemGroup(dispatcher: Dispatcher, { bridge }: CommandGroupOptions): void {
  dispatcher.register("status", async () => {
    const messages = await bridge.systemStatus();
    return { kind: "local", data: { domain: "system", messages } };
  });
}

/** Register the memory domain commands. */
export function registerMemoryGroup(dispatcher: Dispatcher, { bridge }: CommandGroupOptions): void {
  dispatcher.register("memory-digest", async () => {
    const messages = await bridge.memoryDigest();
    return { kind: "local", data: { domain: "memory", messages } };
  });
}

/** Register the model domain commands. */
export function registerModelGroup(dispatcher: Dispatcher, { bridge }: CommandGroupOptions): void {
  dispatcher.register("model-specs", async () => {
    const messages = await bridge.modelSpecs();
    return { kind: "local", data: { domain: "model", messages } };
  });
}

/** Register the selector domain commands. */
export function registerSelectorGroup(dispatcher: Dispatcher, { bridge }: CommandGroupOptions): void {
  dispatcher.register("cells", async () => {
    const messages = await bridge.cellLiveness();
    return { kind: "local", data: { domain: "selector", messages } };
  });
}

/** Register all command groups (settings/system/memory/model/selector). */
export function registerCommandGroups(dispatcher: Dispatcher, options: CommandGroupOptions): void {
  registerSettingsGroup(dispatcher, options);
  registerSystemGroup(dispatcher, options);
  registerMemoryGroup(dispatcher, options);
  registerModelGroup(dispatcher, options);
  registerSelectorGroup(dispatcher, options);
}
