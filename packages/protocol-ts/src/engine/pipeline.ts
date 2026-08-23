/**
 * Pipeline — real multi-stage command execution with output-to-input flow.
 *
 * Replaces the Python3 `_pipeline` parameter-level stub (flagged as E10 in
 * the L2 boundary audit): each stage receives the previous stage's parsed
 * output as structured data, not just a string. The final stage's result
 * is returned to the caller.
 *
 * TS pattern: generic pipeline with typed stage transitions via
 * `PipelineStage<I, O>` — each stage declares its input and output types.
 */

import type { ProtocolBridge } from "./bridge.ts";
import type { ParsedCommand } from "./parser.ts";

/** A single pipeline stage: transforms input into output (or delegates to bridge). */
export interface PipelineStage<I = unknown, O = unknown> {
  /** Stage name for logging/debugging. */
  name: string;
  /** Execute this stage; may delegate to the host via bridge. */
  execute(input: I, ctx: PipelineContext): Promise<O>;
}

/** Context passed to every stage in the pipeline. */
export interface PipelineContext {
  sessionId: string;
  /** Raw text of the original user input (for stages that need context). */
  rawInput: string;
}

/**
 * Create a typed pipeline from an array of stages.
 *
 * ```ts
 * const pipe = pipeline(bridge)
 *   .stage("tokenize", async (line: string) => tokenize(line))
 *   .stage("dispatch", async (tokens: string[]) => dispatch(tokens))
 *   .build();
 * const result = await pipe.execute("status --json");
 * ```
 */
export class Pipeline<I, O> {
  constructor(
    private readonly stages: ReadonlyArray<PipelineStage<any, any>>,
    private readonly bridge: ProtocolBridge,
  ) {}

  /** Execute all stages sequentially; each stage feeds the next. */
  async execute(initialInput: I, ctx: PipelineContext): Promise<O> {
    let current: unknown = initialInput;
    for (const stage of this.stages) {
      current = await stage.execute(current, ctx);
    }
    return current as O;
  }
}

/** Builder for type-safe pipeline construction with progressive typing. */
export class PipelineBuilder<I> {
  private stages: PipelineStage<any, any>[] = [];
  private bridge: ProtocolBridge;

  constructor(bridge: ProtocolBridge) {
    this.bridge = bridge;
  }

  /** Add a pure TS stage (no bridge call). */
  stage<O>(name: string, fn: (input: I, ctx: PipelineContext) => Promise<O>): PipelineBuilder<O> {
    this.stages.push({ name, execute: fn });
    return this as unknown as PipelineBuilder<O>;
  }

  /** Add a bridge-delegating stage that sends a command to the host. */
  bridgeStage<O>(name: string, command: string): PipelineBuilder<O> {
    this.stages.push({
      name,
      execute: async (input: I) => {
        const messages = await this.bridge.command(command, [String(input)]);
        return messages.map((m) => m.payload) as O;
      },
    });
    return this as unknown as PipelineBuilder<O>;
  }

  /** Finalize and return the executable pipeline. */
  build(): Pipeline<I, any> {
    return new Pipeline(this.stages, this.bridge);
  }
}

/** Convenience: start building a pipeline from a string input. */
export function pipeline(bridge: ProtocolBridge): PipelineBuilder<string> {
  return new PipelineBuilder<string>(bridge);
}
