/**
 * DispatchMiddleware — composable pre/post dispatch hook chain.
 *
 * Each middleware can inspect, short-circuit, or observe a command around
 * the dispatcher. All hooks run FIFO for simplicity; the chain is a pure
 * value object composed by `Dispatcher`.
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

  /** Register a pre-dispatch interceptor. */
  useBefore(hook: BeforeHook): this {
    this.beforeHooks.push(hook);
    return this;
  }

  /** Register a post-dispatch observer. */
  useAfter(hook: AfterHook): this {
    this.afterHooks.push(hook);
    return this;
  }

  /** Run before hooks FIFO; returns first non-undefined result (short-circuit). */
  async runBefore(ctx: MiddlewareContext): Promise<CommandResult | undefined> {
    for (const hook of this.beforeHooks) {
      const result = await hook(ctx);
      if (result !== undefined) return result;
    }
    return undefined;
  }

  /** Run after hooks FIFO; never throws. */
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
