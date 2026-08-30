/**
 * Terminal dialect adapter for the TS L2 engine.
 *
 * Mirrors the input surface of Python3 `l2.shells.terminal.TerminalShell`
 * without importing or reimplementing L3/L1 behavior. Local commands are
 * handled by the pure Dispatcher; every side-effecting route is sent through
 * ProtocolBridge and returned as decoded protocol messages.
 */

import type { Message } from "../protocol/wire-envelope.ts";
import type { ProtocolBridge } from "./bridge.ts";
import { CommandHistory, type HistoryEntry } from "./command-history.ts";
import type { CommandCatalog } from "./command-catalog.ts";
import { Dispatcher, type CommandResult } from "./dispatcher.ts";
import { parseRoute, route, type DialectRoute, type RouteOutcome } from "./route.ts";
import { ShellSession } from "./routing-session.ts";

export interface TerminalShellOptions {
  bridge: ProtocolBridge;
  dispatcher?: Dispatcher;
  catalog?: CommandCatalog;
  sessionId?: string;
  historySize?: number;
}

export interface TerminalRunResult {
  /** True when the local route completed or the host result was successful. */
  success: boolean;
  /** Stable result family for renderers and tests. */
  type: "empty" | "local" | "bridge" | "l3a" | "history";
  /** Pure route decision made before any bridge call. */
  route: DialectRoute | RouteOutcome;
  /** Local handler data, when `type` is `local`. */
  data?: Record<string, unknown>;
  /** Decoded host responses, when the route leaves TS. */
  responses: Message[];
  /** Command history view, when `type` is `history`. */
  entries?: readonly HistoryEntry[];
  /** Round-trip plus local dispatch time in milliseconds. */
  elapsedMs: number;
}

export interface TerminalShellSnapshot {
  shell: "terminal";
  session: ReturnType<ShellSession["asDict"]>;
  history_length: number;
}

/** Extract a structured success flag without trusting arbitrary host fields. */
function responseSuccess(messages: readonly Message[]): boolean {
  const first = messages[0]?.payload;
  return typeof first === "object" && first !== null && first.success === false ? false : true;
}

/** Terminal dialect with a local routing session and bounded command history. */
export class TerminalShell {
  public readonly name = "terminal" as const;
  public readonly classifier = (line: string): DialectRoute => this.classify(line);
  public readonly dispatcher: Dispatcher;
  public readonly bridge: ProtocolBridge;
  public readonly catalog?: CommandCatalog;
  private readonly session: ShellSession;
  private readonly history: CommandHistory;

  constructor(options: TerminalShellOptions) {
    this.bridge = options.bridge;
    this.dispatcher = options.dispatcher ?? new Dispatcher();
    this.catalog = options.catalog;
    this.session = this.createSession(options.sessionId ?? this.bridge.sessionId);
    this.history = new CommandHistory(options.historySize ?? 500);
  }

  /** Create an isolated routing session bound to this dialect. */
  createSession(sessionId = ""): ShellSession {
    return new ShellSession({ shell: this.name, sessionId });
  }

  /** Return the default session used when callers do not pass one explicitly. */
  getSession(): ShellSession {
    return this.session;
  }

  /** Pure classifier used by ShellFamily bindings and completion surfaces. */
  classify(line: string): DialectRoute {
    return parseRoute(line);
  }

  /** Expose a detached session/history snapshot for frontend state views. */
  snapshot(): TerminalShellSnapshot {
    return {
      shell: this.name,
      session: this.session.asDict(),
      history_length: this.history.length,
    };
  }

  /** Read history without exposing the mutable internal array. */
  recentHistory(limit = 20): readonly HistoryEntry[] {
    return this.history.recent(limit);
  }

  /** Change the default session's direct target without contacting the host. */
  switchToDirect(cellId: string, agentId: string, sessionId = this.session.session_id): void {
    this.session.switchToDirect(cellId, agentId, sessionId);
  }

  /** Clear the default session's direct target without contacting the host. */
  switchToL3A(): void {
    this.session.switchToL3A();
  }

  /**
   * Execute one terminal line.
   *
   * `help`/`h`, `tools`/`tl`, `status`/`st` and `history`/`hist` retain the
   * Python terminal conveniences. The first three still use the dispatcher or
   * host bridge; only history is local because it is this adapter's input
   * projection.
   */
  async run(text: string, session = this.session): Promise<TerminalRunResult> {
    const line = text.trim();
    if (!line) {
      return { success: true, type: "empty", route: { kind: "empty" }, responses: [], elapsedMs: 0 };
    }

    const started = performance.now();
    const sessionId = session.session_id || this.bridge.sessionId;
    let outcome: TerminalRunResult;

    if (line === "history" || line === "hist") {
      const routeOutcome: DialectRoute = { kind: "engine", name: "history", args: [] };
      outcome = {
        success: true,
        type: "history",
        route: routeOutcome,
        responses: [],
        entries: this.history.recent(),
        elapsedMs: performance.now() - started,
      };
      this.history.record(line, "history", undefined, outcome.elapsedMs);
      return outcome;
    }

    if (line === "help" || line === "h") {
      const local = await this.dispatcher.dispatch({ name: "help", args: [] }, { sessionId });
      if (local.kind === "local") {
        outcome = this.fromDispatcher(local, { kind: "engine", name: "help", args: [] }, started);
      } else {
        outcome = await this.forward(
          local.command,
          local.args,
          { kind: "bridge", name: local.command, args: local.args },
          started,
        );
      }
    } else if (line === "tools" || line === "tl") {
      outcome = await this.forward("tools", [], { kind: "bridge", name: "tools", args: [] }, started);
    } else if (line === "status" || line === "st") {
      outcome = await this.forward(
        "agent_status",
        [],
        { kind: "bridge", name: "agent_status", args: [] },
        started,
      );
    } else {
      const routed = await route(line, {
        dispatcher: this.dispatcher,
        bridge: this.bridge,
        catalog: this.catalog,
        direct: session.isDirect(),
        sessionId,
      });
      if (routed.kind === "local") {
        outcome = {
          success: true,
          type: "local",
          route: routed,
          data: routed.result,
          responses: [],
          elapsedMs: performance.now() - started,
        };
      } else if (routed.kind === "bridge") {
        outcome = await this.forward(routed.name, routed.args, routed, started);
      } else {
        const responses = await this.bridge.l3aSend(routed.text, sessionId);
        outcome = {
          success: responseSuccess(responses),
          type: "l3a",
          route: routed,
          responses,
          elapsedMs: performance.now() - started,
        };
      }
    }

    this.history.record(line, this.historyName(outcome.route), undefined, outcome.elapsedMs);
    return outcome;
  }

  private fromDispatcher(result: CommandResult, fallback: DialectRoute, started: number): TerminalRunResult {
    if (result.kind === "local") {
      return {
        success: true,
        type: "local",
        route: fallback,
        data: result.data,
        responses: [],
        elapsedMs: performance.now() - started,
      };
    }
    return {
      success: true,
      type: "bridge",
      route: { kind: "bridge", name: result.command, args: result.args },
      responses: [],
      elapsedMs: performance.now() - started,
    };
  }

  private async forward(
    name: string,
    args: readonly string[],
    routed: RouteOutcome,
    started: number,
  ): Promise<TerminalRunResult> {
    const responses = await this.bridge.command(name, args);
    return {
      success: responseSuccess(responses),
      type: routed.kind === "l3a" ? "l3a" : "bridge",
      route: routed,
      responses,
      elapsedMs: performance.now() - started,
    };
  }

  private historyName(routed: DialectRoute | RouteOutcome): string {
    switch (routed.kind) {
      case "empty":
        return "";
      case "pipeline":
        return "__pipeline";
      case "system":
        return "__system";
      case "engine":
      case "tool":
        return routed.name;
      case "l3a":
        return "l3a";
      case "local":
      case "bridge":
        return routed.kind;
    }
  }
}
