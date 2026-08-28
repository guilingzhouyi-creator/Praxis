/**
 * Shell route — dialect routing for one input line.
 *
 * Normative routing chain (see docs/architecture/l2-shell-engine.md
 * "Protocol v1 conformance rulings" R6): `$` system → `/` engine command
 * → `|` pipeline → direct tool call → L3A intent. Argument splitting is
 * quote-aware (shlex-compatible subset), so a `|` inside quotes never
 * misroutes into the pipeline.
 */

import type { ProtocolBridge } from "./bridge.ts";
import type { CommandCatalog } from "./command-catalog.ts";
import type { Dispatcher } from "./dispatcher.ts";

/**
 * Split a line on unquoted occurrences of `sep`, honoring single quotes,
 * double quotes, and backslash escapes. Quotes are removed from the
 * resulting segments; escaped separators survive literally.
 */
export function splitUnquoted(text: string, sep: string): string[] {
  const segments: string[] = [];
  let current = "";
  let quote: string | null = null;
  let escaped = false;
  for (const ch of text) {
    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      escaped = true;
      continue;
    }
    if (quote) {
      if (ch === quote) quote = null;
      else current += ch;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === sep) {
      segments.push(current);
      current = "";
      continue;
    }
    current += ch;
  }
  if (escaped) current += "\\";
  segments.push(current);
  return segments;
}

/** Split an argument string on whitespace, honoring quotes and escapes. */
export function splitArgs(text: string): string[] {
  const args: string[] = [];
  let current = "";
  let quote: string | null = null;
  let escaped = false;
  let started = false;
  const flush = () => {
    if (started) args.push(current);
    current = "";
    started = false;
  };
  for (const ch of text) {
    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }
    if (ch === "\\" && !quote) {
      escaped = true;
      started = started || true;
      continue;
    }
    if (quote) {
      if (ch === quote) quote = null;
      else current += ch;
      started = true;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      started = true;
      continue;
    }
    if (/\s/.test(ch)) {
      flush();
      continue;
    }
    current += ch;
    started = true;
  }
  flush();
  return args;
}

/** Pure dialect classification of one input line. */
export type DialectRoute =
  | { kind: "empty" }
  | { kind: "pipeline"; stages: string[] }
  | { kind: "system"; command: string }
  | { kind: "engine"; name: string; args: string[] }
  | { kind: "tool"; name: string; args: string[] }
  | { kind: "l3a"; text: string };

/**
 * Classify one line without executing (pure). Order is normative (R6):
 * `$` system → `/` engine → pipeline → tool (direct) → L3A intent.
 */
export function parseRoute(line: string): DialectRoute {
  const text = line.trim();
  if (!text) return { kind: "empty" };

  if (text.startsWith("$")) {
    return { kind: "system", command: text.slice(1).trim() };
  }

  if (text.startsWith("/")) {
    const rest = text.slice(1).trim();
    const [name, ...args] = splitArgs(rest);
    return { kind: "engine", name: name || "", args };
  }

  // Pipeline detection runs AFTER `$`/`/` so a separator inside a quoted
  // argument or a command name payload can never hijack the line (R6).
  if (splitUnquoted(text, "|").length >= 2) {
    const stages = splitUnquoted(text, "|").map((s) => s.trim()).filter(Boolean);
    if (stages.length >= 2) return { kind: "pipeline", stages };
  }

  // A bare token with arguments is a direct tool call (alias resolution is
  // left to the caller / completer); anything else is an L3A intent.
  const parts = splitArgs(text);
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
  /**
   * Optional shared command catalog. When present, unknown `/engine`
   * names resolve through the alias reverse index first, so an alias of
   * a LOCAL handler executes locally instead of round-tripping to the
   * host (host authority for everything else is unchanged).
   */
  catalog?: CommandCatalog;
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
      if (!handler) {
        // Alias of a LOCAL handler (from commands.yaml metadata): run it
        // locally; everything else still falls through to the bridge.
        const resolved = ctx.catalog?.resolveAlias(parsed.name);
        if (resolved && ctx.dispatcher.has(resolved)) {
          const aliased = await ctx.dispatcher.dispatch(
            { name: resolved, args: parsed.args },
            { sessionId: "s-1" },
          );
          if (aliased.kind === "local") return { kind: "local", result: aliased.data };
          return { kind: "bridge", name: aliased.command, args: aliased.args };
        }
        return { kind: "bridge", name: parsed.name, args: parsed.args };
      }
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
