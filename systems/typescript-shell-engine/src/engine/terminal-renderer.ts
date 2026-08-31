/**
 * Terminal renderer — REPL-neutral output presentation for the TS L2 shell.
 *
 * The renderer consumes `TerminalRunResult` values or decoded protocol
 * response payloads and returns deterministic line records. It does not write
 * stdout, read stdin, create a PTY, execute a command, or own any L3/L1
 * authority. A REPL, TUI, IDE, or HTTP frontend may map the records to its own
 * transport and styling.
 */

import { I18n } from "../i18n/locale-catalog.ts";
import type { Message } from "../protocol/wire-envelope.ts";
import { canonicalJson } from "../protocol/wire-records.ts";
import { SYSTEM_OUTPUT_MAX_CHARS } from "../protocol/wire-types.ts";
import type { HistoryEntry } from "./command-history.ts";
import type { TerminalRunResult } from "./terminal-shell.ts";

/** Python3 parity bound for tool fields shown by the terminal renderer. */
export const TOOL_RESULT_DISPLAY_LIMIT = 5;
/** Python3 parity bound for scalar field text shown by the terminal renderer. */
export const LOG_TRUNC_100 = 100;
/** Python3 parity bound for generic result text shown by the terminal renderer. */
export const LOG_TRUNC_200 = 200;
/** Default history rows shown by a renderer-owned history result. */
export const TERMINAL_HISTORY_DISPLAY_LIMIT = 20;

/** Stable presentation role; frontends may add color or formatting. */
export type TerminalLineRole = "output" | "error";

/** One deterministic line of terminal output, independent of a concrete UI. */
export interface TerminalRenderLine {
  role: TerminalLineRole;
  text: string;
}

/** Rendered result frame returned to a frontend adapter. */
export interface TerminalRenderFrame {
  success: boolean;
  type: TerminalRunResult["type"] | "banner";
  lines: readonly TerminalRenderLine[];
}

export interface TerminalRendererOptions {
  /** Local translation registry; defaults to the TS English subset. */
  i18n?: I18n;
  /** Maximum history rows rendered for a result. */
  historyLimit?: number;
  /** Maximum object fields shown for a tool or generic result. */
  fieldLimit?: number;
}

type UnknownRecord = Record<string, unknown>;

function output(text: string): TerminalRenderLine {
  return { role: "output", text };
}

function errorLine(text: string): TerminalRenderLine {
  return { role: "error", text };
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asRecord(value: unknown): UnknownRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function textValue(value: unknown, limit = LOG_TRUNC_100): string {
  if (typeof value === "string") return value.slice(0, limit);
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    try {
      return canonicalJson(value).slice(0, limit);
    } catch {
      return String(value).slice(0, limit);
    }
  }
  return String(value).slice(0, limit);
}

function splitLines(value: unknown, limit: number = SYSTEM_OUTPUT_MAX_CHARS): string[] {
  const text = asString(value);
  if (!text) return [];
  const clipped = text.slice(0, limit);
  const lines = clipped.split(/\r?\n/);
  if (text.length > limit) lines.push("…");
  return lines;
}

function resultPayloads(messages: readonly Message[]): UnknownRecord[] {
  return messages
    .filter((message) => message.kind === "result")
    .map((message) => asRecord(message.payload))
    .filter((payload): payload is UnknownRecord => payload !== null);
}

/** Render the standard terminal banner as detached line records. */
export function renderTerminalBanner(i18n?: I18n): TerminalRenderFrame {
  const registry = i18n ?? new I18n();
  const translate = registry.t.bind(registry);
  return {
    success: true,
    type: "banner",
    lines: [
      output(translate("terminal.banner.title")),
      output(translate("terminal.banner.l3a")),
      output(translate("terminal.banner.route")),
      output(translate("terminal.banner.scout")),
      output(translate("terminal.banner.system")),
      output(translate("terminal.banner.tool")),
      output(""),
    ],
  };
}

/** Stateless renderer for one terminal result or decoded host response set. */
export class TerminalRenderer {
  private readonly i18n: I18n;
  private readonly historyLimit: number;
  private readonly fieldLimit: number;

  constructor(options: TerminalRendererOptions = {}) {
    this.i18n = options.i18n ?? new I18n();
    this.historyLimit = Math.max(0, options.historyLimit ?? TERMINAL_HISTORY_DISPLAY_LIMIT);
    this.fieldLimit = Math.max(0, options.fieldLimit ?? TOOL_RESULT_DISPLAY_LIMIT);
  }

  /** Render a complete banner without touching a concrete output stream. */
  banner(): TerminalRenderFrame {
    return renderTerminalBanner(this.i18n);
  }

  /** Render a `TerminalShell.run` result into stable line records. */
  render(result: TerminalRunResult): TerminalRenderFrame {
    if (result.type === "empty") {
      return { success: result.success, type: result.type, lines: [] };
    }

    if (result.type === "history") {
      return {
        success: result.success,
        type: result.type,
        lines: this.renderHistory(result.entries ?? []),
      };
    }

    const localPayload = result.type === "local" ? asRecord(result.data) : null;
    const lines = localPayload
      ? this.renderPayload(localPayload, result.route.kind === "engine" ? result.route.name : undefined)
      : this.renderResponses(result.responses);

    if (lines.length > 0) {
      return { success: result.success, type: result.type, lines };
    }

    if (!result.success) {
      return {
        success: false,
        type: result.type,
        lines: [errorLine(this.t("terminal.exec.error", { error: "execution failed" }))],
      };
    }

    return { success: result.success, type: result.type, lines: [] };
  }

  /** Convenience text projection for simple line-oriented frontends. */
  renderText(result: TerminalRunResult): string[] {
    return this.render(result).lines.map((line) => line.text);
  }

  private renderResponses(messages: readonly Message[]): TerminalRenderLine[] {
    const lines: TerminalRenderLine[] = [];
    for (const message of messages) {
      if (message.kind === "result") {
        const payload = asRecord(message.payload);
        if (payload) lines.push(...this.renderPayload(payload));
      } else if (message.kind === "stream_chunk") {
        const payload = asRecord(message.payload);
        const data = payload ? asString(payload.data) : "";
        if (data) lines.push(output(data));
      } else if (message.kind === "event") {
        const payload = asRecord(message.payload);
        if (payload) {
          const eventType = asString(payload.event_type);
          const data = asRecord(payload.data);
          lines.push(output(data ? `${eventType}: ${textValue(data, LOG_TRUNC_200)}` : eventType));
        }
      }
    }
    return lines;
  }

  private renderPayload(payload: UnknownRecord, routeHint?: string): TerminalRenderLine[] {
    switch (asString(payload.type) || routeHint) {
      case "help":
        return this.renderHelp(payload);
      case "tools":
        return this.renderTools(payload);
      case "intent":
        return this.renderIntent(payload);
      case "scout":
        return this.renderScout(payload);
      case "system":
        return this.renderSystem(payload);
      case "tool":
        return this.renderTool(payload);
      default:
        return this.renderGeneric(payload);
    }
  }

  private renderHelp(payload: UnknownRecord): TerminalRenderLine[] {
    const lines = [output(this.t("terminal.help.title"))];
    const commands = Array.isArray(payload.commands) ? payload.commands : [];
    for (const command of commands) {
      if (typeof command === "string") {
        lines.push(output(`  ${command.padEnd(20, " ")}`));
        continue;
      }
      const entry = asRecord(command);
      if (!entry) continue;
      const name = asString(entry.name);
      const help = asString(entry.help);
      lines.push(output(`  ${name.padEnd(20, " ")} ${help}`));
    }
    lines.push(output(this.t("terminal.help.more", { count: String(payload.more ?? 0) })));
    return lines;
  }

  private renderTools(payload: UnknownRecord): TerminalRenderLine[] {
    const lines: TerminalRenderLine[] = [];
    const tools = Array.isArray(payload.tools) ? payload.tools : [];
    for (const tool of tools) {
      const entry = asRecord(tool);
      if (!entry) continue;
      lines.push(output(`  ${asString(entry.name).padEnd(25, " ")} ${asString(entry.description)}`));
    }
    lines.push(output(this.t("terminal.tools.total", { count: String(payload.total ?? tools.length) })));
    return lines;
  }

  private renderIntent(payload: UnknownRecord): TerminalRenderLine[] {
    if (payload.success === true) {
      return [
        output(this.t("terminal.l3a.card", { card_id: asString(payload.card_id, "?") })),
        output(this.t("terminal.l3a.domain", { domain: asString(payload.domain, "?") })),
        output(this.t("terminal.l3a.agent", { agent: asString(payload.agent, "?") })),
        output(this.t("terminal.l3a.type", { card_type: asString(payload.card_type, "?") })),
      ];
    }
    return [errorLine(this.t("terminal.l3a.error", { error: asString(payload.error, "parse failed") }))];
  }

  private renderScout(payload: UnknownRecord): TerminalRenderLine[] {
    if (payload.success !== true) {
      return [errorLine(this.t("terminal.scout.error", { error: asString(payload.error, "?") }))];
    }
    const lines = [output(this.t("terminal.scout.status", { status: asString(payload.status, "?") }))];
    const findings = asStringArray(payload.findings);
    if (findings.length > 0) {
      lines.push(output(this.t("terminal.scout.findings", { count: String(findings.length) })));
      findings.forEach((finding) => lines.push(output(`    - ${finding}`)));
    }
    if (payload.error) lines.push(errorLine(this.t("terminal.scout.error", { error: asString(payload.error) })));
    return lines;
  }

  private renderSystem(payload: UnknownRecord): TerminalRenderLine[] {
    const lines = splitLines(payload.output).map((line) => output(`  ${line}`));
    lines.push(...splitLines(payload.stderr).map((line) => output(this.t("terminal.sys.stderr", { line }))));
    if (payload.error) {
      lines.push(errorLine(this.t("terminal.sys.error", { error: asString(payload.error) })));
    }
    if (payload.timed_out === true) {
      lines.push(errorLine(this.t("terminal.sys.timeout", { timeout: "?" })));
    }
    if (!payload.error && payload.timed_out !== true) {
      lines.push(output(this.t("terminal.sys.exit", { code: String(payload.returncode ?? "?") })));
    }
    return lines;
  }

  private renderTool(payload: UnknownRecord): TerminalRenderLine[] {
    if (payload.success !== true) {
      return [errorLine(this.t("terminal.exec.error", { error: asString(payload.error, "execution failed") }))];
    }
    const data = payload.data ?? payload.result;
    const record = asRecord(data);
    if (!record) {
      return [output(this.t("terminal.exec.result", { result: textValue(data, LOG_TRUNC_200) }))];
    }
    return Object.keys(record)
      .sort()
      .slice(0, this.fieldLimit)
      .map((key) => output(`  ${key}: ${textValue(record[key])}`));
  }

  private renderHistory(entries: readonly HistoryEntry[]): TerminalRenderLine[] {
    return entries
      .slice(0, this.historyLimit)
      .map((entry) => output(`  ${String(entry.seq).padStart(3, " ")}  ${entry.input}`));
  }

  private renderGeneric(payload: UnknownRecord): TerminalRenderLine[] {
    if (payload.success === false) {
      const lines = [errorLine(this.t("terminal.exec.error", { error: asString(payload.error, "execution failed") }))];
      const suggestions = asStringArray(payload.suggestions);
      if (suggestions.length > 0) {
        lines.push(output(`  ${suggestions.slice(0, this.fieldLimit).join(", ")}`));
      }
      return lines;
    }
    const preferred = asString(payload.output) || asString(payload.answer);
    if (preferred) return splitLines(preferred, LOG_TRUNC_200).map(output);
    return Object.keys(payload)
      .filter((key) => !["success", "format"].includes(key))
      .sort()
      .slice(0, this.fieldLimit)
      .map((key) => output(`${key}: ${textValue(payload[key])}`));
  }

  private t(key: string, kwargs: Record<string, string> = {}): string {
    return this.i18n?.t(key, kwargs) ?? key;
  }
}

/** Stateless helper for callers that do not need renderer options. */
export function renderTerminalResult(
  result: TerminalRunResult,
  options?: TerminalRendererOptions,
): TerminalRenderFrame {
  return new TerminalRenderer(options).render(result);
}
