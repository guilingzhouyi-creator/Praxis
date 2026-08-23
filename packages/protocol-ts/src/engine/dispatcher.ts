/** Command registry + dispatcher for the TS engine shell. */

import type { ParsedCommand } from "./parser.ts";

export interface DispatchContext {
  sessionId: string;
}

/**
 * Local handlers return a "local" result; anything unregistered falls back
 * to the bridge marker so the Python3 L3 host stays the authority (the TS
 * shell never re-implements agent loop / tool pipeline / scheduler).
 */
export type CommandResult =
  | { kind: "local"; data: Record<string, unknown> }
  | { kind: "bridge"; command: string; args: string[] };

export type CommandHandler = (args: string[], ctx: DispatchContext) => CommandResult;

export class Dispatcher {
  private readonly handlers = new Map<string, CommandHandler>();
  private sortedNames: string[] | undefined;

  register(name: string, handler: CommandHandler): void {
    this.handlers.set(name, handler);
    // Invalidate the cached sorted listing — registration is rare (once per
    // shell setup) while listCommands() feeds the help builtin on demand.
    this.sortedNames = undefined;
  }

  has(name: string): boolean {
    return this.handlers.has(name);
  }

  /** Registered command names (stable, sorted) — feeds the help builtin. */
  listCommands(): string[] {
    // Cache the sorted listing: command sets are static after registration,
    // and help can be invoked repeatedly in a long-lived session.
    if (this.sortedNames === undefined) {
      this.sortedNames = [...this.handlers.keys()].sort();
    }
    return this.sortedNames;
  }

  /** Dispatch a parsed command; unknown names route to the bridge. */
  dispatch(cmd: ParsedCommand, ctx: DispatchContext): CommandResult {
    const handler = this.handlers.get(cmd.name);
    if (!handler) return { kind: "bridge", command: cmd.name, args: cmd.args };
    return handler(cmd.args, ctx);
  }
}
