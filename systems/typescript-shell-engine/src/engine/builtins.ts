/**
 * Local built-in commands — pure parsing/display only.
 *
 * These never touch L3: they resolve entirely inside the TS shell. Anything
 * else routes through the dispatcher's bridge fallback to the Python3 host.
 */

import type { I18n } from "../locale-catalog.ts";
import type { Dispatcher } from "./dispatcher.ts";

export interface BuiltinOptions {
  /** I18n registry for locale-aware display (lang/help). */
  i18n: I18n;
}

export function registerBuiltins(dispatcher: Dispatcher, options?: BuiltinOptions): void {
  const i18n = options?.i18n;

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
    const names = dispatcher.listCommands();
    if (args.length > 0) {
      return { kind: "local", data: { command: args[0], registered: names.includes(args[0]) } };
    }
    return { kind: "local", data: { commands: names } };
  });

  dispatcher.register("clear", () => ({ kind: "local", data: { cleared: true } }));
}
