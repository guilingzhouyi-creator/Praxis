/**
 * DispatchMiddleware — composable pre/post dispatch hook chain.
 *
 * Mirrors the Python3 tool pipeline's 9-step execution pattern: each
 * middleware can inspect, transform, short-circuit, or observe a command
 * before and after the dispatcher resolves it. Middleware runs in
 * registration order for "before" and reverse order for "after".
 *
 * TS pattern: higher-order function composition with generics. Each
 * middleware receives the parsed command and context, and returns either
 * void (continue) or a CommandResult (short-circuit).
 */

import type { ParsedCommand } from "./parser.ts";
import type { CommandResult, DispatchContext } from "./dispatcher.ts";

export interface MiddlewareContext {
  command: ParsedCommand;
  ctx: DispatchContext;
}

/** Before hook: return a CommandResult to short-circuit, or undefined to continue. */
export type BeforeHook = (
  mw: MiddlewareContext,
) => CommandResult | undefined | Promise<CommandResult | undefined>;

/** After hook: observes the result; cannot modify it (read-only audit trail). */
export type AfterHook = (mw: MiddlewareContext, result: CommandResult) => void;

export class MiddlewareChain {
  private readonly beforeHooks: BeforeHook[] = [];
  private readonly afterHooks: AfterHook[] = [];

  /** Register a pre-dispatch interceptor. Last registered = first executed. */
  useBefore(hook: BeforeHook): this {
    this.beforeHooks.push(hook);
    return this;
  }

  /** Register an post-dispatch observer. Runs in registration order. */
  useAfter(hook: AfterHook): this {
    this.afterHooks.push(hook);
    return this;
  }

  /** Run all before hooks in LIFO order; returns first non-undefined result (short-circuit). */
  async runBefore(ctx: MiddlewareContext): Promise<CommandResult | undefined> {
    for (let i = this.beforeHooks.length - 1; i >= 0; i--) {
      const result = await this.beforeHooks[i](ctx);
      if (result !== undefined) return result;
    }
    return undefined;
  }

  /** Run all after hooks in FIFO order (audit trail). Never throws. */
  runAfter(ctx: MiddlewareContext, result: CommandResult): void {
    for (const hook of this.afterHooks) {
      try {
        hook(ctx, result);
      } catch (err) {
        console.error("[middleware] after-hook error:", err);
      }
    }
  }

  get size(): number {
    return this.beforeHooks.length + this.afterHooks.length;
  }
}
