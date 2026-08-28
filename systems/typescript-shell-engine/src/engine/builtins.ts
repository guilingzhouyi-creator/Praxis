/**
 * Local built-in commands — pure parsing/display only.
 *
 * These never touch L3: they resolve entirely inside the TS shell. Anything
 * else routes through the dispatcher's bridge fallback to the Python3 host.
 */

import type { I18n } from "../locale-catalog.ts";
import type { CommandCatalog } from "./command-catalog.ts";
import type { Dispatcher } from "./dispatcher.ts";
import { helpView } from "./terminal-view.ts";

export interface BuiltinOptions {
  /** I18n registry for locale-aware display (lang/help). */
  i18n?: I18n;
  /** Optional command catalog; when present, help renders the full surface. */
  catalog?: CommandCatalog;
}

/** Register the builtin command set on a dispatcher. */
export function registerBuiltins(dispatcher: Dispatcher, options?: BuiltinOptions): void {
  const i18n = options?.i18n;
  const catalog = options?.catalog;

  dispatcher.register("lang", (args) => {
    if (!i18n) return { kind: "local", data: { lang: "en" } };
    // `lang` → current locale + available; `lang <code>` → switch locale.
    const locale = i18n.getLocale();
    const available = i18n.getAvailableLocales();
    if (args.length > 0) {
      const switched = i18n.setLocale(args[0]);
      return { kind: "local", data: { lang: switched.locale, previous: locale, available } };
    }
    return { kind: "local", data: { lang: locale, available } };
  });

  dispatcher.register("help", (args) => {
    if (catalog) {
      // Full-surface help from the shared commands.yaml metadata: a bare
      // `/help` lists commands with descriptions, `/help <name>` shows
      // one command's details (aliases/args/examples for the frontend).
      if (args.length > 0) {
        const entry = catalog.get(args[0]);
        if (!entry) return { kind: "local", data: { command: args[0], registered: false } };
        return {
          kind: "local",
          data: {
            command: entry.name,
            registered: true,
            help: entry.help,
            category: entry.category,
            aliases: entry.aliases,
            args: entry.args,
            examples: entry.examples,
          },
        };
      }
      return { kind: "local", data: { ...helpView(catalog) } };
    }
    const names = dispatcher.listCommands();
    if (args.length > 0) {
      return { kind: "local", data: { command: args[0], registered: names.includes(args[0]) } };
    }
    return { kind: "local", data: { commands: names } };
  });

  dispatcher.register("clear", () => ({ kind: "local", data: { cleared: true } }));
}
