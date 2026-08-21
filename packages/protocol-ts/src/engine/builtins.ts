/**
 * Local built-in commands — pure parsing/display only.
 *
 * These never touch L3: they resolve entirely inside the TS shell. Anything
 * else routes through the dispatcher's bridge fallback to the Python3 host.
 */

import type { Dispatcher } from "./dispatcher.ts";

export function registerBuiltins(dispatcher: Dispatcher): void {
  dispatcher.register("lang", () => ({ kind: "local", data: { lang: "en" } }));

  dispatcher.register("help", (args) => {
    const names = dispatcher.listCommands();
    if (args.length > 0) {
      return { kind: "local", data: { command: args[0], registered: names.includes(args[0]) } };
    }
    return { kind: "local", data: { commands: names } };
  });

  dispatcher.register("clear", () => ({ kind: "local", data: { cleared: true } }));
}
