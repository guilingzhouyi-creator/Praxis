/**
 * I18n — TS-side locale registry and translation lookup.
 *
 * Mirrors the Python3 i18n surface (src/l2/i18n.py + locales/*.yaml) for
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
  "shell.error.unknown_command": "unknown command: /{cmd}",
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
