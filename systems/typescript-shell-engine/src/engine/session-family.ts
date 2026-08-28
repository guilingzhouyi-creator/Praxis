/**
 * ShellFamily — registry of shell dialects with frontend bindings.
 *
 * Mirrors systems/python-reference-runtime/l2/shells/family.py: shells are declared generically (no
 * dialect hardcoded here), the first registration becomes the default,
 * every structural change bumps a revision counter so consumers can cache
 * snapshots, and frontend names resolve to a dialect with a default
 * fallback. In the TS engine a "shell" is a pure dialect classifier —
 * runtime authority stays on the Python3 host.
 */

/** Minimal shell surface the family needs (a dialect name + optional classifier). */
export interface ShellLike {
  name: string;
  /** Optional pure classifier (e.g. DialectRoute) attached to the dialect. */
  classifier?: (line: string) => unknown;
}

export interface ShellFamilyConfig {
  /** Master switch — False leaves the family empty. */
  enabled?: boolean;
  /** {name: spec} member factories; spec is opaque to the family. */
  shells?: Record<string, unknown>;
  /** {frontend: shell_name} resolution hints. */
  bindings?: Record<string, string>;
  /** Shell used when no binding matches. */
  default?: string;
}

export class ShellFamily {
  private shells = new Map<string, ShellLike>();
  private bindings = new Map<string, string>();
  private defaultName = "";
  private rev = 0;

  /** Register a shell, optionally binding frontends. */
  register(shell: ShellLike, frontends: string[] = []): void {
    if (!shell.name) throw new Error("shell must declare a non-empty name");
    this.shells.set(shell.name, shell);
    for (const frontend of frontends) this.bindings.set(frontend, shell.name);
    if (!this.defaultName) this.defaultName = shell.name;
    this.rev++;
  }

  /** Unregister a shell by name. */
  unregister(name: string): void {
    this.shells.delete(name);
    for (const [frontend, shellName] of [...this.bindings]) {
      if (shellName === name) this.bindings.delete(frontend);
    }
    if (this.defaultName === name) {
      this.defaultName = this.shells.keys().next().value ?? "";
    }
    this.rev++;
  }

  /** Resolve a shell by name, erroring when unknown. */
  get(name: string): ShellLike {
    const shell = this.shells.get(name);
    if (!shell) throw new Error(`unknown shell: ${name}`);
    return shell;
  }

  /** List registered shell names, sorted. */
  list(): string[] {
    return [...this.shells.keys()].sort();
  }

  /** Resolve the default shell, falling back to the first registered. */
  default(): ShellLike {
    if (this.defaultName && this.shells.has(this.defaultName)) return this.shells.get(this.defaultName)!;
    const first = this.shells.values().next().value;
    if (first) return first;
    throw new Error("no shell registered");
  }

  /** Bind a frontend to a shell, erroring on unknown shells. */
  bind(frontend: string, shellName: string): void {
    if (!this.shells.has(shellName)) throw new Error(`unknown shell: ${shellName}`);
    this.bindings.set(frontend, shellName);
    this.rev++;
  }

  /** Resolve the shell for a frontend binding or default. */
  resolve(frontend: string): ShellLike {
    const name = this.bindings.get(frontend) ?? this.defaultName;
    if (name && this.shells.has(name)) return this.shells.get(name)!;
    throw new Error(`no shell for frontend: ${frontend}`);
  }

  /** Apply a config section (enabled/shells/bindings/default); returns members loaded. */
  loadConfig(cfg: ShellFamilyConfig): number {
    if (!cfg || cfg.enabled === false) return 0;
    const declared = cfg.shells ?? {};
    let count = 0;
    for (const [name, spec] of Object.entries(declared)) {
      if (typeof spec !== "object" || spec === null) continue;
      this.register({ name });
      count++;
    }
    const bindings = cfg.bindings ?? {};
    for (const [frontend, shellName] of Object.entries(bindings)) {
      if (this.shells.has(shellName)) this.bindings.set(frontend, shellName);
    }
    if (cfg.default && this.shells.has(cfg.default)) this.defaultName = cfg.default;
    if (Object.keys(bindings).length > 0 || cfg.default) this.rev++;
    return count;
  }

  /** Return the family revision counter. */
  revision(): number {
    return this.rev;
  }

  /** Snapshot the family state for diagnostics. */
  snapshot(): { shells: string[]; bindings: Record<string, string>; default: string; revision: number } {
    return {
      shells: this.list(),
      bindings: Object.fromEntries(this.bindings),
      default: this.defaultName,
      revision: this.rev,
    };
  }
}
