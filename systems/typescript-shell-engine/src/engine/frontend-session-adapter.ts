/**
 * Frontend session adapter — compose the TS L2 session, terminal dialect, and
 * renderer without creating a concrete UI or taking execution authority.
 *
 * The adapter is intentionally thin: SessionView owns only the client-side
 * view cursor, TerminalShell owns one-line dialect routing, and
 * TerminalRenderer owns detached line records. The Python3/Rust host remains
 * authoritative for session state, replay, tools, processes, and AgentLoop
 * execution.
 */

import type { ProtocolBridge } from "./bridge.ts";
import { registerBuiltins } from "./builtins.ts";
import { Dispatcher } from "./dispatcher.ts";
import {
  project,
  SessionView,
  type SessionState,
} from "./interactive-session.ts";
import {
  TerminalRenderer,
  type TerminalRenderFrame,
  type TerminalRendererOptions,
} from "./terminal-renderer.ts";
import {
  TerminalShell,
  type TerminalRunResult,
} from "./terminal-shell.ts";
import {
  TerminalInputController,
  type TerminalInputControllerOptions,
  type TerminalInputSnapshot,
} from "./terminal-input-controller.ts";

/** Frontend identities supported by the shared L2 session adapter. */
export const FRONTEND_KINDS = ["web", "tui", "desktop", "vscode", "ssh"] as const;
export type FrontendKind = (typeof FRONTEND_KINDS)[number];
/** Default number of chunk submissions allowed in the serialized queue. */
export const FRONTEND_INPUT_MAX_PENDING = 64 as const;

/** Projection shape available from the shared session projection module. */
type ProjectionKind = Exclude<FrontendKind, "ssh">;

export interface FrontendSessionAdapterOptions {
  bridge: ProtocolBridge;
  sessionId?: string;
  viewId: string;
  frontend: FrontendKind;
  /** Reuse a caller-owned terminal shell when the frontend has one. */
  shell?: TerminalShell;
  /** Optional i18n/field-limit configuration for line rendering. */
  renderer?: TerminalRenderer;
  rendererOptions?: TerminalRendererOptions;
  /** Optional caller-owned chunk framer for a concrete frontend transport. */
  input?: TerminalInputController;
  inputOptions?: TerminalInputControllerOptions;
  /** Maximum active + queued feed/finish operations (default: 64). */
  maxPendingInputs?: number;
}

/** Combined one-line execution and detached output frame. */
export interface FrontendRunResult {
  frontend: FrontendKind;
  input: string;
  run: TerminalRunResult;
  frame: TerminalRenderFrame;
}

/** Detached session state suitable for a concrete frontend transport. */
export interface FrontendSessionSnapshot {
  frontend: FrontendKind;
  session_id: string;
  view_id: string;
  last_acked: number;
  identity: Record<string, unknown>;
  projection: Record<string, unknown>;
}

/** Thin composition layer shared by web/TUI/desktop/IDE/SSH adapters. */
export class FrontendSessionAdapter {
  public readonly bridge: ProtocolBridge;
  public readonly sessionId: string;
  public readonly viewId: string;
  public readonly frontend: FrontendKind;
  public readonly shell: TerminalShell;
  public readonly renderer: TerminalRenderer;
  public readonly input: TerminalInputController;
  private readonly view: SessionView;
  private attached = false;
  private inputQueue: Promise<void> = Promise.resolve();
  private readonly maxPendingInputs: number;
  private pendingInputs = 0;

  constructor(options: FrontendSessionAdapterOptions) {
    this.bridge = options.bridge;
    this.sessionId = options.sessionId ?? options.bridge.sessionId;
    this.viewId = options.viewId;
    this.frontend = options.frontend;
    this.shell = options.shell ?? this.defaultShell();
    this.renderer = options.renderer
      ?? new TerminalRenderer(options.rendererOptions);
    this.input = options.input ?? new TerminalInputController(options.inputOptions);
    this.maxPendingInputs = options.maxPendingInputs ?? FRONTEND_INPUT_MAX_PENDING;
    if (!Number.isInteger(this.maxPendingInputs) || this.maxPendingInputs < 1) {
      throw new Error(`maxPendingInputs must be a positive integer, got ${String(this.maxPendingInputs)}`);
    }
    this.view = new SessionView(this.viewId, this.bridge);
  }

  /** Attach this frontend view to the host-owned session and replay it once. */
  async attach(): Promise<FrontendSessionSnapshot> {
    await this.view.attach(this.sessionId);
    this.attached = true;
    return this.sync();
  }

  /** Fetch the current host replay window and project it for this frontend. */
  async sync(): Promise<FrontendSessionSnapshot> {
    this.requireAttached();
    const state = await this.view.state(this.sessionId);
    return this.snapshotFromState(state);
  }

  /** Submit one line and return both raw route data and detached presentation. */
  async submit(input: string): Promise<FrontendRunResult> {
    const run = await this.shell.run(input);
    return {
      frontend: this.frontend,
      input,
      run,
      frame: this.renderer.render(run),
    };
  }

  /**
   * Frame a frontend text chunk and submit complete lines in arrival order.
   *
   * Calls are serialized so concurrent WebSocket/SSH callbacks cannot reorder
   * lines. The controller remains transport-neutral and never reads the
   * frontend source itself.
   */
  feedInput(chunk: string): Promise<FrontendRunResult[]> {
    return this.enqueueInput(async () => {
      const results: FrontendRunResult[] = [];
      for (const line of this.input.feed(chunk)) {
        results.push(await this.submit(line));
      }
      return results;
    });
  }

  /** Flush an unterminated final line on frontend EOF. */
  finishInput(): Promise<FrontendRunResult[]> {
    return this.enqueueInput(async () => {
      const results: FrontendRunResult[] = [];
      for (const line of this.input.finish()) {
        results.push(await this.submit(line));
      }
      return results;
    });
  }

  /** Reset the frontend input boundary after EOF or a recoverable fault. */
  resetInput(): void {
    this.input.reset();
  }

  /** Advance this view's host cursor without mutating another frontend view. */
  async ack(ackSeq: number): Promise<void> {
    this.requireAttached();
    await this.view.ack(this.sessionId, ackSeq);
  }

  /** Detach this view; host session state remains intact for other views. */
  async detach(): Promise<void> {
    if (!this.attached) return;
    await this.view.detach(this.sessionId);
    this.attached = false;
  }

  /** Return the current client-side cursor and shell snapshot without I/O. */
  localSnapshot(): {
    frontend: FrontendKind;
    session_id: string;
    view_id: string;
    last_acked: number;
    shell: ReturnType<TerminalShell["snapshot"]>;
    input: TerminalInputSnapshot;
    pending_inputs: number;
    max_pending_inputs: number;
  } {
    return {
      frontend: this.frontend,
      session_id: this.sessionId,
      view_id: this.viewId,
      last_acked: this.view.lastAcked,
      shell: this.shell.snapshot(),
      input: this.input.snapshot(),
      pending_inputs: this.pendingInputs,
      max_pending_inputs: this.maxPendingInputs,
    };
  }

  /** Render the standard banner without writing to an output stream. */
  banner(): TerminalRenderFrame {
    return this.renderer.banner();
  }

  private snapshotFromState(state: SessionState): FrontendSessionSnapshot {
    const projectionKind: ProjectionKind = this.frontend === "ssh" ? "tui" : this.frontend;
    return {
      frontend: this.frontend,
      session_id: this.sessionId,
      view_id: this.viewId,
      last_acked: this.view.lastAcked,
      identity: { ...state.identity },
      projection: project(projectionKind, state),
    };
  }

  private defaultShell(): TerminalShell {
    const dispatcher = new Dispatcher();
    registerBuiltins(dispatcher);
    return new TerminalShell({
      bridge: this.bridge,
      dispatcher,
      sessionId: this.sessionId,
    });
  }

  private requireAttached(): void {
    if (!this.attached) {
      throw new Error(`frontend view is not attached: ${this.viewId}`);
    }
  }

  private enqueueInput(operation: () => Promise<FrontendRunResult[]>): Promise<FrontendRunResult[]> {
    if (this.pendingInputs >= this.maxPendingInputs) {
      return Promise.reject(
        new Error(`frontend input queue is full: ${this.maxPendingInputs} pending operations`),
      );
    }
    this.pendingInputs += 1;
    const run = this.inputQueue.then(operation);
    this.inputQueue = run.then(() => undefined, () => undefined);
    return run.then(
      (result) => {
        this.pendingInputs -= 1;
        return result;
      },
      (error) => {
        this.pendingInputs -= 1;
        throw error;
      },
    );
  }
}
