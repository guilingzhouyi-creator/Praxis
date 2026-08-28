/**
 * Completer — local tab-completion candidate rendering.
 *
 * Mirrors systems/python-reference-runtime/l2/shell_completer.py
 * TerminalCompleter: matches command
 * names, tool names and aliases by prefix, plus filesystem-style partials
 * after a space. Pure local logic — candidate source data (tool registry,
 * shell_aliases config) comes from the host via bridge, never owned here.
 * When a CommandCatalog is injected, its command names and aliases are
 * merged into the candidates (same source the Python completer uses).
 */

import type { CommandCatalog } from "./command-catalog.ts";

/** Builtin command names always available (mirrors shell_completer builtins). */
export const BUILTIN_COMMANDS = ["help", "exit", "clear", "history", "tools", "status"];

/** Default alias map (mirrors shell_completer._load_aliases fallback). */
export const DEFAULT_ALIASES: Record<string, string> = {
  rf: "read_file",
  wf: "write_file",
  ls: "list_directory",
  g: "grep",
  glob: "glob",
  cat: "read_file",
  h: "help",
  q: "exit",
  st: "status",
  tl: "tools",
  clr: "clear",
  hist: "history",
};

export interface CompleterOptions {
  /** Tool names from the host tool registry (sorted). */
  toolNames?: string[];
  /** Alias map (defaults to DEFAULT_ALIASES). */
  aliases?: Record<string, string>;
  /** Optional command catalog; command names + aliases join the candidates. */
  catalog?: CommandCatalog;
}

export class Completer {
  private toolNames: string[];
  private aliases: Record<string, string>;
  private catalog: CommandCatalog | undefined;

  constructor(options: CompleterOptions = {}) {
    this.toolNames = options.toolNames ?? [];
    this.aliases = options.aliases ?? DEFAULT_ALIASES;
    this.catalog = options.catalog;
  }

  /** All candidate names: tools + builtins + aliases + catalog names. */
  candidates(): string[] {
    const names = new Set<string>([
      ...this.toolNames,
      ...BUILTIN_COMMANDS,
      ...Object.keys(this.aliases),
      ...(this.catalog?.commandNames() ?? []),
      ...(this.catalog?.aliases() ?? []),
    ]);
    return [...names].sort();
  }

  /**
   * Complete a partial line. Returns all matches for the current token:
   * - no space yet → prefix-match against command/tool/alias candidates
   * - after a space → filesystem-style partials (., .., /)
   */
  complete(line: string): string[] {
    const trimmed = line.trimStart();
    if (trimmed.includes(" ")) {
      const partial = trimmed.split(/\s+/).pop() ?? "";
      return [".", "..", "/"].filter((p) => p.startsWith(partial));
    }
    return this.candidates().filter((c) => c.startsWith(trimmed));
  }
}
