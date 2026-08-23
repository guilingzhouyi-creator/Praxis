/**
 * Shell route — dialect routing for one input line.
 *
 * Mirrors the Python3 routing chain (src/l2/l2_shell/__init__.py dispatch +
 * src/l2/shells/terminal.py TerminalShell.run): pipeline, `$` system, `/`
 * engine command, direct tool call, and the L3A intent fallback. The route
 * classifies a line purely (parseRoute) and executes it against the
 * dispatcher + bridge (route); the host stays the authority for anything
 * beyond local parsing/display.
 */

import type { ProtocolBridge } from "./bridge.ts";
import type { Dispatcher } from "./dispatcher.ts";

/** Pure dialect classification of one input line. */
export type DialectRoute =
  | { kind: "empty" }
  | { kind: "pipeline"; stages: string[] }
  | { kind: "system"; command: string }
  | { kind: "engine"; name: string; args: string[] }
  | { kind: "tool"; name: string; args: string[] }
  | { kind: "l3a"; text: string };

/**
 * Classify one line without executing (pure). Order mirrors Python3:
 * pipeline → `$` system → `/` engine → tool (direct) → L3A intent.
 */
export function parseRoute(line: string): DialectRoute {
  const text = line.trim();
  if (!text) return { kind: "empty" };

  if (text.includes("|")) {
    const stages = text.split("|").map((s) => s.trim()).filter(Boolean);
    if (stages.length >= 2) return { kind: "pipeline", stages };
  }

  if (text.startsWith("$")) {
    return { kind: "system", command: text.slice(1).trim() };
  }

  if (text.startsWith("/")) {
    const rest = text.slice(1).trim();
    const [name, ...args] = rest.split(/\s+/);
    return { kind: "engine", name: name || "", args };
  }

  // A bare token with arguments is a direct tool call (alias resolution is
  // left to the caller / completer); anything else is an L3A intent.
  const parts = text.split(/\s+/);
  if (parts.length >= 1 && parts[0].length > 0) {
    return { kind: "tool", name: parts[0], args: parts.slice(1) };
  }
  return { kind: "l3a", text };
}

export interface RouteContext {
  dispatcher: Dispatcher;
  bridge: ProtocolBridge;
  /** Direct-mode flag; when false, bare text routes to L3A intent. */
  direct?: boolean;
}

export type RouteOutcome =
  | { kind: "local"; result: Record<string, unknown> }
  | { kind: "bridge"; name: string; args: string[] }
  | { kind: "l3a"; text: string };

/**
 * Execute one line: local engine commands resolve in the dispatcher,
 * anything else routes to the bridge (host authority) or L3A fallback.
 */
export async function route(line: string, ctx: RouteContext): Promise<RouteOutcome> {
  const parsed = parseRoute(line);
  switch (parsed.kind) {
    case "empty":
      return { kind: "local", result: { success: true, type: "empty" } };
    case "pipeline":
      // Pipeline semantics live on the host; forward the stages verbatim.
      return { kind: "bridge", name: "__pipeline", args: parsed.stages };
    case "system":
      return { kind: "bridge", name: "__system", args: [parsed.command] };
    case "engine": {
      const handler = ctx.dispatcher.has(parsed.name);
      if (!handler) return { kind: "bridge", name: parsed.name, args: parsed.args };
      const result = await ctx.dispatcher.dispatch({ name: parsed.name, args: parsed.args }, { sessionId: "s-1" });
      if (result.kind === "local") return { kind: "local", result: result.data };
      return { kind: "bridge", name: result.command, args: result.args };
    }
    case "tool":
      // Direct tool call: without direct mode the tool still needs the host
      // capability gate — forward as a tool command over the bridge.
      return { kind: "bridge", name: parsed.name, args: parsed.args };
    case "l3a":
      return { kind: "l3a", text: parsed.text };
  }
}
