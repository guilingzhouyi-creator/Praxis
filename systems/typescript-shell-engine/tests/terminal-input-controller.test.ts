/**
 * Terminal input controller tests — chunk framing without stdin or PTY I/O.
 */

import { describe, expect, it } from "vitest";
import {
  TerminalInputController,
  TerminalInputControllerError,
} from "../src/engine/terminal-input-controller.ts";

describe("TerminalInputController", () => {
  it("assembles fragmented chunks and preserves empty lines", () => {
    const controller = new TerminalInputController();
    expect(controller.feed("hel")).toEqual([]);
    expect(controller.feed("lo\n\nwor")).toEqual(["hello", ""]);
    expect(controller.finish()).toEqual(["wor"]);
    expect(controller.snapshot()).toMatchObject({ buffer: "", buffered_bytes: 0, finished: true });
  });

  it("normalizes LF, CRLF and CR boundaries across chunks", () => {
    const controller = new TerminalInputController();
    expect(controller.feed("one\r")).toEqual(["one"]);
    expect(controller.feed("")).toEqual([]);
    expect(controller.feed("\ntwo\rthree\n")).toEqual(["two", "three"]);
    expect(controller.feed("four\r\nfive")).toEqual(["four"]);
    expect(controller.finish()).toEqual(["five"]);
  });

  it("counts UTF-8 bytes and accepts a surrogate pair split across chunks", () => {
    const controller = new TerminalInputController({ maxLineBytes: 4 });
    expect(controller.feed("\ud83d")).toEqual([]);
    expect(controller.feed("\ude00\n")).toEqual(["😀"]);
    expect(controller.snapshot().buffered_bytes).toBe(0);
  });

  it("rejects an oversized line and requires reset after finish", () => {
    const controller = new TerminalInputController({ maxLineBytes: 3 });
    expect(() => controller.feed("abcd")).toThrow(TerminalInputControllerError);
    expect(controller.snapshot().buffer).toBe("");
    expect(() => controller.finish()).not.toThrow();
    expect(() => controller.feed("x")).toThrow(/finished/);
    controller.reset();
    expect(controller.feed("ok\n")).toEqual(["ok"]);
  });

  it("rejects invalid limits", () => {
    expect(() => new TerminalInputController({ maxLineBytes: 0 })).toThrow(/maxLineBytes/);
    expect(() => new TerminalInputController({ maxLineBytes: Number.MAX_SAFE_INTEGER })).toThrow(/maxLineBytes/);
  });
});
