/**
 * Bounded decision-provider adapter for the TypeScript L3 coordinator.
 *
 * Providers are coordination dependencies, not execution authorities. This
 * adapter gives a provider a detached input/context, an explicit deadline and
 * a cancellation signal; all process, terminal, tool, and capability effects
 * must still be returned as data-only actions for AgentRuntime to send to Rust.
 */

import type {
  AgentDecision,
  AgentDecisionContext,
  AgentDecisionPort,
  AgentInput,
} from "../contracts/agent-contracts.ts";
import {
  AgentRuntimeError,
  copyAgentDecisionContext,
  copyAgentInput,
} from "../contracts/agent-contracts.ts";
/** Default decision-provider deadline for one L3 turn. */
export const L3_MAX_DECISION_LATENCY_MS = 30_000;
/** Maximum timer-safe provider deadline supported by the JS runtime. */
export const L3_MAX_DECISION_LATENCY_LIMIT_MS = 2_147_483_647;

/** Provider request carrying an explicit deadline and bounded work metadata. */
export interface DecisionProviderRequest {
  readonly input: AgentInput;
  readonly context: AgentDecisionContext;
  readonly deadlineAt: number;
  readonly budget: {
    readonly maxLatencyMs: number;
    readonly inputBytes: number;
    readonly historyEntries: number;
  };
}

/** Provider implementation contract; it cannot execute kernel side effects. */
export interface DecisionProvider {
  decide(request: DecisionProviderRequest): Promise<AgentDecision>;
}

/** Outcome labels emitted by the provider adapter's optional telemetry sink. */
export type DecisionProviderOutcome = "completed" | "failed" | "cancelled" | "timeout";

/** Bounded provider telemetry, intentionally free of prompt/content payloads. */
export interface DecisionProviderTelemetry {
  readonly elapsedMs: number;
  readonly outcome: DecisionProviderOutcome;
  readonly inputBytes: number;
  readonly historyEntries: number;
}

/** Adapter configuration for deadlines, clocks, and diagnostics. */
export interface DecisionProviderOptions {
  readonly maxLatencyMs?: number;
  readonly clock?: () => number;
  readonly onTelemetry?: (event: DecisionProviderTelemetry) => void;
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function validateLatency(value: number): number {
  if (
    !Number.isSafeInteger(value)
    || value < 1
    || value > L3_MAX_DECISION_LATENCY_LIMIT_MS
  ) {
    throw new AgentRuntimeError(
      "decision_failed",
      `maxLatencyMs must be a positive safe integer <= ${L3_MAX_DECISION_LATENCY_LIMIT_MS}`,
    );
  }
  return value;
}

function emitTelemetry(
  sink: DecisionProviderOptions["onTelemetry"],
  event: DecisionProviderTelemetry,
): void {
  try {
    sink?.(event);
  } catch {
    // Telemetry is a bypass: diagnostics cannot turn a provider result into
    // a runtime failure or obscure the original outcome.
  }
}

/**
 * Wrap a provider with detached context, cancellation, and a hard deadline.
 *
 * The returned value implements the existing AgentDecisionPort so callers can
 * add the boundary without changing AgentRuntime's orchestration contract.
 */
export function createBoundedDecisionPort(
  provider: DecisionProvider,
  options: DecisionProviderOptions = {},
): AgentDecisionPort {
  const maxLatencyMs = validateLatency(options.maxLatencyMs ?? L3_MAX_DECISION_LATENCY_MS);
  const clock = options.clock ?? (() => Date.now() / 1000);

  return {
    async decide(input, context): Promise<AgentDecision> {
      if (context.signal?.aborted) {
        throw new AgentRuntimeError("cancelled", "agent decision was cancelled before provider admission");
      }

      const detachedInput = copyAgentInput(input);
      const detachedContext = copyAgentDecisionContext(context);
      const providerController = new AbortController();
      const providerContext: AgentDecisionContext = {
        ...detachedContext,
        input: copyAgentInput(detachedContext.input),
        identity: { ...detachedContext.identity },
        history: detachedContext.history.map((record) => ({ ...record })),
        signal: providerController.signal,
      };
      const inputBytes = utf8Bytes(detachedInput.text);
      const historyEntries = providerContext.history.length;
      const request: DecisionProviderRequest = {
        input: detachedInput,
        context: providerContext,
        deadlineAt: clock() + maxLatencyMs / 1000,
        budget: { maxLatencyMs, inputBytes, historyEntries },
      };

      let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
      let removeAbortListener = (): void => undefined;
      let outcome: DecisionProviderOutcome = "completed";
      const startedAt = Date.now();

      let providerPromise: Promise<AgentDecision>;
      try {
        // Start the provider synchronously after admission. Deferring this
        // call to a microtask creates a cancellation race where an immediate
        // caller abort happens before the provider can observe its signal.
        providerPromise = Promise.resolve(provider.decide(request));
      } catch (error) {
        providerPromise = Promise.reject(error);
      }
      const timeoutPromise = new Promise<AgentDecision>((_, reject) => {
        timeoutHandle = setTimeout(() => {
          outcome = "timeout";
          providerController.abort();
          reject(new AgentRuntimeError("decision_timeout", "agent decision exceeded its deadline"));
        }, maxLatencyMs);
      });
      const cancellationPromise = new Promise<AgentDecision>((_, reject) => {
        const onAbort = (): void => {
          outcome = "cancelled";
          providerController.abort();
          reject(new AgentRuntimeError("cancelled", "agent decision was cancelled"));
        };
        if (context.signal) {
          context.signal.addEventListener("abort", onAbort, { once: true });
          removeAbortListener = () => context.signal?.removeEventListener("abort", onAbort);
        }
      });

      try {
        return await Promise.race([providerPromise, timeoutPromise, cancellationPromise]);
      } catch (error) {
        if (outcome === "completed") outcome = "failed";
        if (error instanceof AgentRuntimeError) throw error;
        throw new AgentRuntimeError(
          "decision_failed",
          error instanceof Error ? error.message : "agent decision provider failed",
        );
      } finally {
        if (timeoutHandle !== undefined) clearTimeout(timeoutHandle);
        removeAbortListener();
        emitTelemetry(options.onTelemetry, {
          elapsedMs: Math.max(0, Date.now() - startedAt),
          outcome,
          inputBytes,
          historyEntries,
        });
      }
    },
  };
}
