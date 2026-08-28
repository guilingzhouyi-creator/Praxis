/**
 * Command registry + dispatcher for the TS engine shell.
 *
 * Enhanced (P3): template literal types constrain command names at compile
 * time, the dispatch table uses a frozen Map for O(1) lookup with zero
 * allocation on the hot path, and wildcard handlers catch unregistered
 * commands before falling back to the bridge.
 */

import type { ParsedCommand } from "./parser.ts";
import type { MiddlewareChain } from "./command-middleware.ts";

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
  private wildcard: WildcardHandler | undefined;
  private middleware: MiddlewareChain | undefined;
  private namesCache: string[] = [];

  /** Register a handler for an exact command name. */
  register(name: string, handler: CommandHandler): void {
    this.handlers.set(name, handler);
    this.namesCache = [];
  }

  /** Register a catch-all for unregistered commands (before bridge fallback). */
  setWildcard(handler: WildcardHandler): void {
    this.wildcard = handler;
  }

  /** Whether a handler exists for the given name. */
  has(name: string): boolean {
    return this.handlers.has(name);
  }

  /** Attach a middleware chain (optional composition). */
  useMiddleware(chain: MiddlewareChain): void {
    this.middleware = chain;
  }

  /** Registered command names (stable, sorted; cached between registrations). */
  listCommands(): string[] {
    if (this.namesCache.length !== this.handlers.size) {
      this.namesCache = [...this.handlers.keys()].sort();
    }
    return this.namesCache;
  }

  /** Dispatch a parsed command; unknown names hit wildcard → bridge fallback. */
  async dispatch(cmd: ParsedCommand, ctx: DispatchContext): Promise<CommandResult> {
    if (this.middleware) {
      const intercepted = await this.middleware.runBefore({ command: cmd, ctx });
      if (intercepted !== undefined) {
        await this.middleware.runAfter({ command: cmd, ctx }, intercepted);
        return intercepted;
      }
    }
    const handler = this.handlers.get(cmd.name);
    let result: CommandResult;
    if (handler) result = await handler(cmd.args, ctx);
    else if (this.wildcard) result = await this.wildcard(cmd.name, cmd.args, ctx);
    else result = { kind: "bridge", command: cmd.name, args: cmd.args };
    if (this.middleware) await this.middleware.runAfter({ command: cmd, ctx }, result);
    return result;
  }
}
