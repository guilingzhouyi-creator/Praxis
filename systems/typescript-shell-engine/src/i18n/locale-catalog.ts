/**
 * I18n — TS-side locale registry and translation lookup.
 *
 * Mirrors the Python3 i18n surface
 * (systems/python-reference-runtime/l2/i18n.py + locales/*.yaml) for
 * the TS engine's local-only needs: locale switching (lang builtin) and
 * display-string translation of the shell command help. The Python3 host
 * stays the authority for full translation data; this module carries the
 * locale metadata plus the en dictionary subset the TS shell renders
 * locally (help/clear/lang), keyed by the same dot-notation used by
 * l2.i18n.t().
 */

export interface I18nOptions {
  /** Dot-notation dictionary, e.g. { "shell.command.help": "Show commands" }. */
  dictionary?: Record<string, string>;
  /** Available locale codes (mirrors l2.i18n.get_available_locales). */
  available?: string[];
  /** Initial locale (default "en"). */
  defaultLocale?: string;
}

/** en dictionary subset — mirrors locales/en.yaml keys for local builtins. */
const EN_DICTIONARY: Record<string, string> = {
  "shell.command.help": "Show available commands",
  "shell.command.clear": "Clear the screen",
  "shell.command.lang": "Show current locale / switch locale",
  "shell.command.tools": "List registered tools",
  "shell.command.status": "Show session status",
  "shell.error.unknown_command": "unknown command: /{cmd}",
  // Terminal dialect display strings — values synchronized with the
  // authoritative locales/en.yaml "terminal:" section (never drift).
  "terminal.banner.title": "Agent OS Terminal — Type 'help' for commands, 'exit' to quit",
  "terminal.banner.l3a": "/intent <text>  → L3A direct session",
  "terminal.banner.route": "/intent <text>@<cell>/<agent> → Route to specific Cell/Agent",
  "terminal.banner.scout": "/scout <task>  → Scout investigation",
  "terminal.banner.system": "$ <command>  → Raw system command (Bash/PowerShell)",
  "terminal.banner.tool": "<tool> <args>  → Tool execution (aliases: rf→read_file)",
  "terminal.help.title": "Commands:",
  "terminal.help.more": "... and {count} more tools (type 'tools' to list all)",
  "terminal.tools.total": "Total: {count} tools",
  "terminal.l3a.parsing": "[L3A] Parsing: {intent}",
  "terminal.l3a.routing": "[L3A] Routing to {target}/{agent}: {intent}",
  "terminal.l3a.card": "[L3A] Card: {card_id}",
  "terminal.l3a.domain": "        Domain: {domain}",
  "terminal.l3a.agent": "        Agent: {agent}",
  "terminal.l3a.type": "        Type: {card_type}",
  "terminal.l3a.error": "[L3A] Error: {error}",
  "terminal.scout.usage": "[Scout] Usage: !scout <task>",
  "terminal.scout.commissioning": "[Scout] Commissioning: {task}",
  "terminal.scout.disabled": "[Scout] Delegation disabled: scout is not available to {agent}",
  "terminal.scout.status": "[Scout] Status: {status}",
  "terminal.scout.findings": "[Scout] Findings ({count}):",
  "terminal.scout.error": "[Scout] Error: {error}",
  "terminal.sys.stderr": "[stderr] {line}",
  "terminal.sys.exit": "[Exit] {code}",
  "terminal.sys.timeout": "[Error] Command timed out after {timeout}s",
  "terminal.sys.shell_not_found": "[Error] Shell not found",
  "terminal.sys.error": "[Error] {error}",
  "terminal.exec.prefix": "[Exec] {tool} {args}",
  "terminal.exec.result": "  Result: {result}",
  "terminal.exec.error": "[Error] {error}",
  "terminal.exec.unknown_tool": "[Error] Unknown tool: {tool}",
  // Selector preconnect verdict labels (defined here first; Python3
  // locales/*.yaml carry the same keys).
  "selector.denied": "connection denied: {reason}",
  "selector.risk.high": "high injection risk",
  "selector.risk.medium": "medium injection risk",
  "selector.risk.none": "no injection risk",
};

export class I18n {
  private dictionary: Record<string, string>;
  private locale: string;
  private readonly available: string[];

  constructor(options: I18nOptions = {}) {
    this.dictionary = { ...EN_DICTIONARY, ...(options.dictionary ?? {}) };
    this.available = options.available ?? ["en", "ja", "ko", "zh-CN"];
    this.locale = options.defaultLocale ?? "en";
  }

  getLocale(): string {
    return this.locale;
  }

  /** Switch locale; unknown codes fall back to "en" and report the change. */
  setLocale(locale: string): { locale: string; available: string[] } {
    this.locale = this.available.includes(locale) ? locale : "en";
    return { locale: this.locale, available: [...this.available] };
  }

  getAvailableLocales(): string[] {
    return [...this.available];
  }

  /**
   * Translate a dot-notation key for the current locale. The TS shell only
   * ships the en dictionary; other locales fall back to the key itself
   * (same behavior as Python3 when a translation is missing).
   */
  t(key: string, kwargs: Record<string, string> = {}): string {
    const template = this.dictionary[key] ?? key;
    return template.replace(/\{(\w+)\}/g, (_, name: string) => kwargs[name] ?? `{${name}}`);
  }
}
