/**
 * I18n + lang builtin tests: locale registry, translation lookup, and the
 * locale-switching behavior of the lang command (local-only, no bridge).
 */

import { describe, expect, it } from "vitest";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { registerBuiltins } from "../src/engine/builtins.ts";
import { I18n } from "../src/locale-catalog.ts";

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
