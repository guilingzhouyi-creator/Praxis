/**
 * ShellFamily tests: registration, bindings, default fallback, revision
 * counting, config loading and snapshot immutability.
 */

import { describe, expect, it } from "vitest";
import { ShellFamily, type ShellLike } from "../src/engine/session-family.ts";

function shell(name: string): ShellLike {
  return { name, classifier: (line: string) => ({ name, line }) };
}

describe("ShellFamily", () => {
  it("registers shells with frontend bindings; first registration is default", () => {
    const family = new ShellFamily();
    family.register(shell("terminal"), ["web", "tui"]);
    family.register(shell("desktop"), ["desktop"]);
    expect(family.list()).toEqual(["desktop", "terminal"]);
    expect(family.default().name).toBe("terminal");
    expect(family.resolve("web").name).toBe("terminal");
    expect(family.resolve("desktop").name).toBe("desktop");
  });

  it("resolve falls back to the default for unbound frontends", () => {
    const family = new ShellFamily();
    family.register(shell("terminal"), ["web"]);
    expect(family.resolve("ssh").name).toBe("terminal");
  });

  it("bind and unregister update bindings, default and revision", () => {
    const family = new ShellFamily();
    family.register(shell("a"));
    family.register(shell("b"));
    const r0 = family.revision();
    family.bind("web", "b");
    expect(family.resolve("web").name).toBe("b");
    expect(family.revision()).toBeGreaterThan(r0);

    family.unregister("a");
    expect(family.list()).toEqual(["b"]);
    expect(family.default().name).toBe("b");
    expect(() => family.get("a")).toThrow(/unknown shell/);
  });

  it("loadConfig honors enabled=false and applies bindings/default", () => {
    const family = new ShellFamily();
    const loaded = family.loadConfig({
      enabled: true,
      shells: { terminal: {}, desktop: {} },
      bindings: { web: "terminal" },
      default: "desktop",
    });
    expect(loaded).toBe(2);
    expect(family.resolve("web").name).toBe("terminal");
    expect(family.default().name).toBe("desktop");
    expect(family.revision()).toBeGreaterThan(0);

    const disabled = new ShellFamily();
    expect(disabled.loadConfig({ enabled: false, shells: { x: {} } })).toBe(0);
    expect(disabled.list()).toEqual([]);
  });

  it("snapshot is a plain copy (immutable surface)", () => {
    const family = new ShellFamily();
    family.register(shell("terminal"), ["web"]);
    const snap = family.snapshot();
    expect(snap).toEqual({
      shells: ["terminal"],
      bindings: { web: "terminal" },
      default: "terminal",
      revision: 1,
    });
    // Mutating the returned object must not affect the family.
    snap.bindings.web = "hacked";
    expect(family.resolve("web").name).toBe("terminal");
  });

  it("classifier travels with the resolved shell", () => {
    const family = new ShellFamily();
    family.register(shell("terminal"));
    const resolved = family.resolve("tui");
    expect(resolved.classifier?.("hello")).toEqual({ name: "terminal", line: "hello" });
  });
});
