/**
 * Output guard — display-safety mirror of agent responses.
 *
 * Mirrors systems/python-reference-runtime/l2/l2_shell/output_guard.py:
 * an optional callback intercepts
 * agent output before display and may allow, block with a replacement, or
 * block with a truncated fallback. The guard is a display-side mirror only
 * — the Python3 host owns the real safety decision; this module renders
 * the outcome for local frontends and degrades to allow-through when no
 * guard is registered.
 */

/** Truncation length when a guard blocks without a replacement (LOG_TRUNC_100). */
export const OUTPUT_GUARD_TRUNC = 100;

/** Guard callback contract (mirrors Python3 set_output_guard). */
export type OutputGuardCallback = (
  agentId: string,
  response: string,
) => { safe: boolean; replacement?: string } | undefined;

export interface GuardResult {
  safe: boolean;
  output: string;
}

export class OutputGuard {
  private callback: OutputGuardCallback | undefined;

  /** Register the intercepting callback (undefined clears it). */
  setGuard(callback: OutputGuardCallback | undefined): void {
    this.callback = callback;
  }

  /**
   * Pass agent output through the registered guard, or allow if none set.
   * - no guard / guard throws → safe, original response
   * - guard allows → original response
   * - guard blocks w/ replacement → replacement text
   * - guard blocks w/o replacement → first 100 chars of original
   */
  guardOutput(agentId: string, response: string): GuardResult {
    if (!this.callback) return { safe: true, output: response };
    try {
      const result = this.callback(agentId, response);
      if (result && result.safe === false) {
        const replacement = result.replacement ?? "";
        return { safe: false, output: replacement || response.slice(0, OUTPUT_GUARD_TRUNC) };
      }
      return { safe: true, output: response };
    } catch {
      // Guard failure must never break display (degrade to allow-through).
      return { safe: true, output: response };
    }
  }
}
