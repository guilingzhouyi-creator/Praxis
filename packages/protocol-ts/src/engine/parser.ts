/** Parse one shell input line into a command name and arguments. */

export interface ParsedCommand {
  name: string;
  args: string[];
}

/**
 * Tokenize on whitespace with double-quote grouping, mirroring the Python3
 * shell's split semantics for the TS engine's parser module.
 */
export function tokenize(input: string): string[] {
  const tokens: string[] = [];
  const pattern = /"([^"]*)"|(\S+)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(input)) !== null) {
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
