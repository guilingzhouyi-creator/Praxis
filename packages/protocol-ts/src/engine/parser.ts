/** Parse one shell input line into a command name and arguments. */

export interface ParsedCommand {
  name: string;
  args: string[];
}

// Module-level pattern: parsing is a hot path (every input line), and a
// per-call regex literal would recompile on each invocation.
const TOKEN_PATTERN = /"([^"]*)"|(\S+)/g;

/**
 * Tokenize on whitespace with double-quote grouping, mirroring the Python3
 * shell's split semantics for the TS engine's parser module.
 */
export function tokenize(input: string): string[] {
  const tokens: string[] = [];
  TOKEN_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = TOKEN_PATTERN.exec(input)) !== null) {
    tokens.push(match[1] ?? match[2]);
  }
  return tokens;
}

/** Split one line into a command name and its argument list. */
export function parseLine(line: string): ParsedCommand {
  const trimmed = line.trim();
  if (!trimmed) return { name: "", args: [] };
  const parts = tokenize(trimmed);
  const name = parts.shift() ?? "";
  return { name, args: parts };
}
