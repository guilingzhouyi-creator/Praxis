/**
 * DispatchMiddleware — composable pre/post dispatch hook chain.
 *
 * Inspired by the Python3 tool pipeline (9-step): each middleware can
 * inspect, short-circuit, or observe a command around the dispatcher.
 * Before hooks run LIFO (last registered = first executed, so the
 * outermost layer wraps inner ones); after hooks run FIFO for a stable
 * audit trail. This module is a pure chain — the dispatcher composes it.
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

/** After hook: observes the result; may be async, cannot modify it. */
export type AfterHook = (
  mw: MiddlewareContext,
  result: CommandResult,
) => void | Promise<void>;

/**
 * Ordered chain of before/after hooks composable with `Dispatcher`.
 *
 * Dispatchers that support middleware should call `runBefore` before
 * handler lookup and `runAfter` after resolution. The chain is reusable
 * and `size` reflects total hooks.
 */
export class MiddlewareChain {
  private readonly beforeHooks: BeforeHook[] = [];
  private readonly afterHooks: AfterHook[] = [];

  /** Register a pre-dispatch interceptor. Last registered = outermost (LIFO). */
  useBefore(hook: BeforeHook): this {
    this.beforeHooks.push(hook);
    return this;
  }

  /** Register a post-dispatch observer. Runs FIFO for stable audit trail. */
  useAfter(hook: AfterHook): this {
    this.afterHooks.push(hook);
    return this;
  }

  /** Run all before hooks LIFO; returns first non-undefined result (short-circuit). */
  async runBefore(ctx: MiddlewareContext): Promise<CommandResult | undefined> {
    for (let i = this.beforeHooks.length - 1; i >= 0; i--) {
      const result = await this.beforeHooks[i](ctx);
      if (result !== undefined) return result;
    }
    return undefined;
  }

  /** Run all after hooks FIFO; never throws; awaits async observers. */
  async runAfter(ctx: MiddlewareContext, result: CommandResult): Promise<void> {
    for (const hook of this.afterHooks) {
      try {
        await hook(ctx, result);
      } catch (err) {
        console.error("[middleware] after-hook error:", err);
      }
    }
  }

  /** Total hooks registered (before + after). */
  get size(): number {
    return this.beforeHooks.length + this.afterHooks.length;
  }

  /** Remove all hooks (test reset). */
  clear(): void {
    this.beforeHooks.length = 0;
    this.afterHooks.length = 0;
  }
}
