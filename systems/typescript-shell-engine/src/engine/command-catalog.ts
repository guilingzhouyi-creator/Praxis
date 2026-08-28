/**
 * CommandCatalog — local shell command metadata registry.
 *
 * Mirrors the Python3 CommandRegistry metadata surface
 * (systems/python-reference-runtime/l2/commands.py) for LOCAL display
 * needs only: `/help` rendering, alias reverse lookup, and
 * unknown-command suggestions. The Python3 host stays the authority for
 * command EXECUTION — this module never registers handlers, it only
 * parses and indexes the shared `config/commands.yaml` metadata.
 *
 * YAML subset: the parser intentionally supports only the shapes that
 * appear in config/commands.yaml — a top-level command map, two-space
 * scalar/flow-list fields, and four-space dash list items (quoted
 * strings, bare strings, and flow-style argument maps). Anything else is
 * skipped defensively: a malformed entry degrades to absence, never to a
 * crash.
 */

/** One command's metadata, mirroring CommandDef (commands.py). */
export interface CommandEntry {
  name: string;
  category: string;
  help: string;
  aliases: string[];
  args: CommandArg[];
  examples: string[];
}

/** One positional/flag argument of a command (commands.yaml args items). */
export interface CommandArg {
  name: string;
  completer: string;
  optional: boolean;
  description: string;
}

/** Commands shown by `/help` before the "more" tail (SHELL_AUTOCOMPLETE_DISPLAY_LIMIT). */
export const HELP_DISPLAY_LIMIT = 15;

/** Strip a YAML comment; `#` counts only outside quotes and at a word start. */
function stripComment(line: string): string {
  let quote: string | null = null;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === "#" && (i === 0 || /\s/.test(line[i - 1] ?? ""))) return line.slice(0, i);
  }
  return line;
}

/** Unwrap a quoted YAML scalar, resolving `\"` and `\'` escapes. */
function unquote(raw: string): string {
  return raw.replace(/\\(["'])/g, "$1");
}

/** Parse a scalar value: quoted string, boolean, or bare token. */
function parseScalar(raw: string): string | boolean {
  const s = raw.trim();
  if (s === "true") return true;
  if (s === "false") return false;
  if (s.length >= 2 && ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'")))) {
    return unquote(s.slice(1, -1));
  }
  return s;
}

/** Split a flow sequence/object body on commas outside quotes. */
function splitFlow(body: string): string[] {
  const parts: string[] = [];
  let current = "";
  let quote: string | null = null;
  let depth = 0;
  for (const ch of body) {
    if (quote) {
      current += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === "{" || ch === "[") depth++;
    if (ch === "}" || ch === "]") depth--;
    if (ch === "," && depth === 0) {
      parts.push(current);
      current = "";
      continue;
    }
    current += ch;
  }
  if (current.trim()) parts.push(current);
  return parts;
}

/** Parse a flow list like `["ls", "dc"]` into plain values. */
function parseFlowList(raw: string): (string | boolean)[] {
  const s = raw.trim();
  if (!s.startsWith("[") || !s.endsWith("]")) return [];
  return splitFlow(s.slice(1, -1)).map(parseScalar);
}

/** Parse a flow object like `{name: x, optional: true}` into a field map. */
function parseFlowObject(raw: string): Record<string, string | boolean> {
  const s = raw.trim();
  if (!s.startsWith("{") || !s.endsWith("}")) return {};
  const out: Record<string, string | boolean> = {};
  for (const part of splitFlow(s.slice(1, -1))) {
    const colon = part.indexOf(":");
    if (colon <= 0) continue;
    const key = part.slice(0, colon).trim();
    if (!key) continue;
    const value = parseScalar(part.slice(colon + 1));
    out[key] = typeof value === "boolean" ? value : value.trim();
  }
  return out;
}

/** Normalize a raw flow-object arg item into a CommandArg. */
function toCommandArg(raw: unknown): CommandArg | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, string | boolean>;
  if (typeof r.name !== "string" || !r.name) return null;
  return {
    name: r.name,
    completer: typeof r.completer === "string" ? r.completer : "",
    optional: r.optional === true,
    description: typeof r.description === "string" ? r.description : "",
  };
}

/** Normalize a raw command field value into its typed CommandEntry slot. */
function toArg(entry: CommandEntry, field: string, value: unknown): void {
  switch (field) {
    case "category":
      entry.category = typeof value === "string" ? value : "other";
      break;
    case "help":
      entry.help = typeof value === "string" ? value : "";
      break;
    case "aliases":
      entry.aliases = Array.isArray(value) ? value.filter((a): a is string => typeof a === "string") : [];
      break;
    case "args":
      entry.args = Array.isArray(value) ? value.map(toCommandArg).filter((a): a is CommandArg => a !== null) : [];
      break;
    case "examples":
      entry.examples = Array.isArray(value) ? value.filter((e): e is string => typeof e === "string") : [];
      break;
    default:
      break;
  }
}

/**
 * Command metadata index with alias reverse lookup and revision counting.
 *
 * Revision semantics mirror the Python registry: every mutation bumps a
 * counter so consumers (completer, help view) can cache derived indexes.
 */
export class CommandCatalog {
  private entries = new Map<string, CommandEntry>();
  private aliasIndex = new Map<string, string>();
  private namesCache: string[] = [];
  private rev = 0;

  /** Parse commands.yaml text and replace the current metadata (returns count). */
  loadDefaults(yamlText: string): number {
    this.entries.clear();
    let current: CommandEntry | null = null;
    let listField: string | null = null;
    const pushListItem = (value: unknown): void => {
      if (!current || !listField) return;
      switch (listField) {
        case "aliases":
          if (typeof value === "string") current.aliases.push(value);
          break;
        case "args":
          current.args.push(value as CommandArg);
          break;
        case "examples":
          if (typeof value === "string") current.examples.push(value);
          break;
        default:
          break;
      }
    };
    for (const rawLine of yamlText.split("\n")) {
      const line = stripComment(rawLine).trimEnd();
      if (!line.trim()) continue;
      const indent = line.length - line.trimStart().length;
      const content = line.trim();
      if (indent === 0) {
        const top = content.match(/^([A-Za-z0-9_.-]+):\s*(.*)$/);
        if (!top) continue;
        current = {
          name: top[1],
          category: "other",
          help: "",
          aliases: [],
          args: [],
          examples: [],
        };
        this.entries.set(current.name, current);
        listField = null;
        continue;
      }
      if (!current) continue;
      if (indent === 2) {
        const field = content.match(/^([A-Za-z0-9_.-]+):\s*(.*)$/);
        if (!field) continue;
        listField = null;
        const key = field[1];
        const rest = field[2].trim();
        if (rest.startsWith("[")) {
          toArg(current, key, parseFlowList(rest));
        } else if (rest) {
          toArg(current, key, parseScalar(rest));
        } else {
          toArg(current, key, []);
          listField = key;
        }
        continue;
      }
      if (indent === 4 && content.startsWith("-") && listField) {
        const item = content.slice(1).trim();
        pushListItem(item.startsWith("{") ? toCommandArg(parseFlowObject(item)) : parseScalar(item));
      }
    }
    this.rev++;
    this.rebuildAliasIndex();
    return this.entries.size;
  }

  /** O(1) reverse lookup: alias → canonical command name. */
  resolveAlias(alias: string): string | undefined {
    return this.aliasIndex.get(alias);
  }

  /** All registered aliases (for completer candidates). */
  aliases(): string[] {
    return [...this.aliasIndex.keys()].sort();
  }

  /** Sorted command names (stable, cached between revisions). */
  commandNames(): string[] {
    if (this.namesCache.length !== this.entries.size) {
      this.namesCache = [...this.entries.keys()].sort();
    }
    return this.namesCache;
  }

  get(name: string): CommandEntry | undefined {
    return this.entries.get(name);
  }

  has(name: string): boolean {
    return this.entries.has(name);
  }

  /** All entries sorted by name (help view input). */
  list(): CommandEntry[] {
    return this.commandNames().map((n) => this.entries.get(n)!).filter(Boolean);
  }

  /** Structural revision — bumped on every loadDefaults. */
  revision(): number {
    return this.rev;
  }

  private rebuildAliasIndex(): void {
    this.aliasIndex.clear();
    for (const entry of this.entries.values()) {
      for (const alias of entry.aliases) this.aliasIndex.set(alias, entry.name);
    }
  }
}

/** Parse commands.yaml text into a fresh catalog (convenience factory). */
export function parseCommandCatalog(yamlText: string): CommandCatalog {
  const catalog = new CommandCatalog();
  catalog.loadDefaults(yamlText);
  return catalog;
}