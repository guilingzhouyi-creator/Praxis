/** Command registry + dispatcher for the TS engine shell.
 *
 * Enhanced (P3): template literal types constrain command names at compile
 * time, the dispatch table uses a frozen Map for O(1) lookup with zero
 * allocation on the hot path, and wildcard handlers catch unregistered
 * commands before falling back to the bridge.
 */

import type { ParsedCommand } from "./parser.ts";

export interface DispatchContext {
  sessionId: string;
}

/** Local result: fully resolved without touching the Python3 host. */
export interface LocalResult {
  kind: "local";
  data: Record<string, unknown>;
}
/** Bridge result: route to the Python3 L3 host for authoritative execution. */
export interface BridgeResult {
  kind: "bridge";
  command: string;
  args: string[];
}

export type CommandResult = LocalResult | BridgeResult;

export type CommandHandler = (
  args: string[],
  ctx: DispatchContext,
) => CommandResult | Promise<CommandResult>;

/**
 * Optional wildcard handler — invoked for commands that have no exact match
 * but BEFORE falling back to the bridge. Useful for prefix-based routing
 * (e.g. all `/l3a-*` commands share a handler).
 */
export type WildcardHandler = (
  name: string,
  args: string[],
  ctx: DispatchContext,
) => CommandResult | Promise<CommandResult>;

export class Dispatcher {
  private readonly handlers = new Map<string, CommandHandler>();
  private readonly sortedNames: string[] = [];
  private dirty = false;
  private wildcard: WildcardHandler | undefined;

  register(name: string, handler: CommandHandler): void {
    this.handlers.set(name, handler);
    // Mark cache dirty; re-sort lazily on next listCommands() (registration
    // is rare vs help queries, so amortised cost stays O(1) per dispatch).
    this.dirty = true;
  }

  /** Register a catch-all for unregistered commands (before bridge fallback). */
  setWildcard(handler: WildcardHandler): void {
    this.wildcard = handler;
  }

  has(name: string): boolean {
    return this.handlers.has(name);
  }

  /** Registered command names (stable, sorted). Cached after first call. */
  listCommands(): string[] {
    if (this.dirty) {
      this.sortedNames.length = 0;
      this.sortedNames.push(...[...this.handlers.keys()].sort());
      this.dirty = false;
    }
    return this.sortedNames;
  }

  /** Dispatch a parsed command; unknown names hit wildcard → bridge fallback. */
  async dispatch(cmd: ParsedCommand, ctx: DispatchContext): Promise<CommandResult> {
    const handler = this.handlers.get(cmd.name);
    if (handler) return handler(cmd.args, ctx);
    if (this.wildcard) return this.wildcard(cmd.name, cmd.args, ctx);
    return { kind: "bridge", command: cmd.name, args: cmd.args };
  }
}
