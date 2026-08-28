/**
 * TerminalView — dict-to-view projections for the terminal dialect.
 *
 * Mirrors the RESULT SHAPES produced by the Python3 TerminalShell
 * (systems/python-reference-runtime/l2/shells/terminal.py) and its
 * `/intent` / `/scout` helpers: every projection takes a plain payload
 * dict (from the host via the bridge) and returns a normalized display
 * shape with the same keys. Pure functions — no authority, no rendering,
 * no I/O; rendering and truncation stay with the consuming frontend.
 */

import { HELP_DISPLAY_LIMIT, type CommandCatalog } from "./command-catalog.ts";

/** Truncation bound for long strings in views (LOG_TRUNC_200 in params/system.py). */
export const LOG_TRUNC_200 = 200;
/** Max scout findings surfaced per commission (SCOUT_FINDINGS_DISPLAY_LIMIT). */
export const SCOUT_FINDINGS_DISPLAY_LIMIT = 5;

export interface HelpView {
  success: boolean;
  type: "help";
  commands: { name: string; help: string }[];
  more: number;
}

export interface ToolsView {
  success: boolean;
  type: "tools";
  tools: { name: string; description: string }[];
  total: number;
}

export interface IntentView {
  success: boolean;
  type: "intent";
  intent: string;
  card_id: string;
  domain: string;
  agent: string;
  card_type: string;
  error?: string;
}

export interface ScoutView {
  success: boolean;
  type: "scout";
  task: string;
  status: string;
  findings: string[];
  error?: string;
}

export interface SystemView {
  success: boolean;
  type: "system";
  command: string;
  output: string;
  stderr: string;
  returncode: number | null;
  timed_out?: boolean;
  error?: string;
}

export interface ToolView {
  success: boolean;
  type: "tool";
  tool: string;
  args: Record<string, string>;
  data: unknown;
  error?: string;
}

/** Safe string coercion; misses become "" (mirrors Python dict .get defaults). */
function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Safe number coercion; misses become null (mirrors Python .get defaults). */
function asNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

/** Build the `/help` view from catalog metadata (mirrors TerminalShell._help_result). */
export function helpView(catalog: CommandCatalog): HelpView {
  const names = catalog.commandNames().slice(0, HELP_DISPLAY_LIMIT);
  const commands = names.map((name) => ({ name, help: catalog.get(name)?.help ?? "" }));
  return { success: true, type: "help", commands, more: Math.max(0, catalog.commandNames().length - commands.length) };
}

/** Build the `/tools` view (mirrors TerminalShell._tools_result success shape). */
export function toolsView(tools: { name: string; description: string }[]): ToolsView {
  return { success: true, type: "tools", tools, total: tools.length };
}

/** Project a capability `/intent` payload (mirrors intent_direct result keys). */
export function intentView(payload: Record<string, unknown>): IntentView {
  return {
    success: payload.success === true,
    type: "intent",
    intent: asString(payload.intent),
    card_id: asString(payload.card_id).length > 0 ? asString(payload.card_id) : "?",
    domain: asString(payload.domain).length > 0 ? asString(payload.domain) : "?",
    agent: asString(payload.agent).length > 0 ? asString(payload.agent) : "?",
    card_type: asString(payload.card_type).length > 0 ? asString(payload.card_type) : "?",
    ...(payload.error !== undefined ? { error: asString(payload.error) } : {}),
  };
}

/** Project a `/scout` commission payload (mirrors scout_commission result keys). */
export function scoutView(payload: Record<string, unknown>): ScoutView {
  const rawFindings = Array.isArray(payload.findings) ? payload.findings : [];
  const findings = rawFindings
    .map((f) => asString(f).slice(0, LOG_TRUNC_200))
    .slice(0, SCOUT_FINDINGS_DISPLAY_LIMIT);
  return {
    success: payload.success === true,
    type: "scout",
    task: asString(payload.task),
    status: asString(payload.status).length > 0 ? asString(payload.status) : "?",
    findings,
    ...(payload.error !== undefined ? { error: asString(payload.error) } : {}),
  };
}

/** Project a `$` system execution payload (mirrors _system_result keys). */
export function systemView(payload: Record<string, unknown>): SystemView {
  const view: SystemView = {
    success: payload.success === true,
    type: "system",
    command: asString(payload.command),
    output: asString(payload.output),
    stderr: asString(payload.stderr),
    returncode: asNumber(payload.returncode),
    ...(payload.timed_out === true ? { timed_out: true } : {}),
    ...(payload.error !== undefined ? { error: asString(payload.error) } : {}),
  };
  return view;
}

/** Project a direct tool-call payload (mirrors _tool_result keys). */
export function toolResultView(payload: Record<string, unknown>): ToolView {
  const rawArgs = payload.args;
  return {
    success: payload.success === true,
    type: "tool",
    tool: asString(payload.tool),
    args: rawArgs !== null && typeof rawArgs === "object" ? (rawArgs as Record<string, string>) : {},
    data: payload.data ?? payload.result ?? null,
    ...(payload.error !== undefined ? { error: asString(payload.error) } : {}),
  };
}