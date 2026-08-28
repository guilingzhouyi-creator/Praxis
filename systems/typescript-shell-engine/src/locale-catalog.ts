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

/** en dictionary subset — matches locales/en.yaml keys for local builtins. */
const EN_DICTIONARY: Record<string, string> = {
  "shell.command.help": "Show available commands",
  "shell.command.clear": "Clear the screen",
  "shell.command.lang": "Show current locale / switch locale",
  "shell.command.tools": "List registered tools",
  "shell.command.status": "Show session status",
  "shell.error.unknown_command": "unknown command: /{cmd}",
  // Terminal dialect display strings (first defined here; the Python3
  // REPL renders these keys verbatim until locales/*.yaml catch up).
  "terminal.help.title": "Commands",
  "terminal.help.more": "{count} more commands",
  "terminal.tools.total": "{count} tools registered",
  "terminal.sys.exit": "exit {code}",
  "terminal.sys.stderr": "[stderr] {line}",
  "terminal.exec.error": "execution failed: {error}",
  "terminal.exec.result": "{result}",
  "terminal.l3a.card": "card {card_id}",
  "terminal.l3a.domain": "domain {domain}",
  "terminal.l3a.agent": "agent {agent_id}",
  "terminal.l3a.type": "type {card_type}",
  "terminal.l3a.error": "intent failed: {error}",
  "terminal.scout.status": "scout status: {status}",
  "terminal.scout.findings": "{count} findings",
  "terminal.scout.error": "scout failed: {error}",
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
