/**
 * I18n + lang builtin tests: locale registry, translation lookup, and the
 * locale-switching behavior of the lang command (local-only, no bridge).
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { registerBuiltins } from "../src/engine/builtins.ts";
import { I18n } from "../src/locale-catalog.ts";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const EN_YAML_PATH = path.join(REPO_ROOT, "locales", "en.yaml");

describe("I18n", () => {
  it("defaults to en with the standard available locales", async () => {
    const i18n = new I18n();
    expect(i18n.getLocale()).toBe("en");
    expect(i18n.getAvailableLocales()).toEqual(["en", "ja", "ko", "zh-CN"]);
  });

  it("translates dot-notation keys and substitutes kwargs", async () => {
    const i18n = new I18n();
    expect(i18n.t("shell.command.help")).toBe("Show available commands");
    // The en template already carries the leading slash (unknown command: /{cmd}).
    expect(i18n.t("shell.error.unknown_command", { cmd: "nope" })).toBe("unknown command: /nope");
  });

  it("falls back to the key itself when no translation exists", async () => {
    const i18n = new I18n();
    expect(i18n.t("shell.command.nonexistent")).toBe("shell.command.nonexistent");
  });

  it("switches locale, rejecting unknown codes with an en fallback", async () => {
    const i18n = new I18n();
    const switched = i18n.setLocale("zh-CN");
    expect(switched.locale).toBe("zh-CN");
    expect(switched.available).toContain("zh-CN");
    expect(i18n.setLocale("xx-XX").locale).toBe("en");
  });
});

describe("lang builtin", () => {
  function setup(): { dispatcher: Dispatcher; i18n: I18n } {
    const dispatcher = new Dispatcher();
    const i18n = new I18n();
    registerBuiltins(dispatcher, { i18n });
    return { dispatcher, i18n };
  }

  it("reports current locale and available locales", async () => {
    const { dispatcher } = setup();
    const out = await dispatcher.dispatch({ name: "lang", args: [] }, { sessionId: "s-1" });
    expect(out).toEqual({
      kind: "local",
      data: { lang: "en", available: ["en", "ja", "ko", "zh-CN"] },
    });
  });

  it("switches locale with an argument and reports the previous one", async () => {
    const { dispatcher } = setup();
    const out = await dispatcher.dispatch({ name: "lang", args: ["ja"] }, { sessionId: "s-1" });
    expect(out).toEqual({
      kind: "local",
      data: { lang: "ja", previous: "en", available: ["en", "ja", "ko", "zh-CN"] },
    });
    // The switch persisted on the shared I18n instance.
    const again = await dispatcher.dispatch({ name: "lang", args: [] }, { sessionId: "s-1" });
    expect(again).toMatchObject({ data: { lang: "ja" } });
  });

  it("degrades to the plain en reply when no i18n is injected", async () => {
    const dispatcher = new Dispatcher();
    registerBuiltins(dispatcher);
    const out = await dispatcher.dispatch({ name: "lang", args: [] }, { sessionId: "s-1" });
    expect(out).toEqual({ kind: "local", data: { lang: "en" } });
  });
});

describe("en dictionary parity with locales/en.yaml", () => {
  it("keeps every terminal/selector key in sync with the authoritative yaml", () => {
    if (!existsSync(EN_YAML_PATH)) return; // repo layout unavailable
    const expected = parseTerminalSelectorKeys(readFileSync(EN_YAML_PATH, "utf8"));
    const keys = Object.keys(expected);
    expect(keys.length).toBeGreaterThan(30); // sanity: the yaml sections are present
    const i18n = new I18n();
    for (const key of keys) {
      // t() without kwargs keeps the {placeholder} spines verbatim.
      expect(i18n.t(key), `key ${key}`).toBe(expected[key]);
    }
  });
});

/** Extract `terminal.*` / `selector.*` leaf keys from the en.yaml subset. */
function parseTerminalSelectorKeys(yamlText: string): Record<string, string> {
  const out: Record<string, string> = {};
  let top: string | null = null;
  let section: string | null = null;
  for (const rawLine of yamlText.split("\n")) {
    if (!rawLine.trim() || rawLine.trim().startsWith("#")) continue;
    const topMatch = rawLine.match(/^([a-z][a-z0-9_-]*):\s*$/);
    if (topMatch) {
      top = ["terminal", "selector"].includes(topMatch[1]) ? topMatch[1] : null;
      section = null;
      continue;
    }
    if (!top) continue;
    const sectionMatch = rawLine.match(/^  ([a-z0-9_]+):\s*$/);
    if (sectionMatch) {
      section = sectionMatch[1];
      continue;
    }
    const leafMatch = rawLine.match(/^    ([a-z0-9_]+):\s*(.+)$/);
    if (leafMatch) {
      const value = leafMatch[2].trim().replace(/^["']|["']$/g, "");
      out[`${top}.${section}.${leafMatch[1]}`] = value;
    }
  }
  return out;
}
