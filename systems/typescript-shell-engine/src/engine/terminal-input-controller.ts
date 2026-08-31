/**
 * REPL-neutral terminal input framing for the TS L2 shell.
 *
 * Frontends deliver text chunks; this controller turns them into complete
 * lines without reading stdin, creating a PTY, or executing a command. It
 * deliberately preserves the line text and leaves trimming, routing, history,
 * and side effects to `TerminalShell`.
 */

import { MAX_FRAME_BYTES } from "../protocol/wire-types.ts";

const UTF8_ENCODER = new TextEncoder();

/** Default maximum UTF-8 bytes retained for one unfinished input line. */
export const TERMINAL_INPUT_MAX_LINE_BYTES = MAX_FRAME_BYTES;

export interface TerminalInputControllerOptions {
  /** Maximum UTF-8 bytes retained for one line (default: protocol frame cap). */
  maxLineBytes?: number;
}

/** Detached state useful for frontend diagnostics and recovery. */
export interface TerminalInputSnapshot {
  buffer: string;
  buffered_bytes: number;
  finished: boolean;
}

/** Fail-closed input framing error. */
export class TerminalInputControllerError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TerminalInputControllerError";
  }
}

function byteLength(value: string): number {
  return UTF8_ENCODER.encode(value).byteLength;
}

function isHighSurrogate(code: number): boolean {
  return code >= 0xd800 && code <= 0xdbff;
}

function isLowSurrogate(code: number): boolean {
  return code >= 0xdc00 && code <= 0xdfff;
}

/**
 * Add two UTF-8 lengths while correcting a surrogate pair split across
 * frontend chunks. `TextEncoder` encodes each lone surrogate as three bytes,
 * while the completed pair is four bytes.
 */
function joinedByteLength(left: string, leftBytes: number, right: string, rightBytes: number): number {
  if (!left || !right) return leftBytes + rightBytes;
  const leftCode = left.charCodeAt(left.length - 1);
  const rightCode = right.charCodeAt(0);
  return leftBytes + rightBytes
    - (isHighSurrogate(leftCode) && isLowSurrogate(rightCode) ? 2 : 0);
}

/** Chunk-to-line boundary adapter shared by all concrete frontends. */
export class TerminalInputController {
  private buffer = "";
  private bufferedBytes = 0;
  private skipLfAfterCr = false;
  private finished = false;
  private readonly maxLineBytes: number;

  constructor(options: TerminalInputControllerOptions = {}) {
    const maxLineBytes = options.maxLineBytes ?? TERMINAL_INPUT_MAX_LINE_BYTES;
    if (!Number.isInteger(maxLineBytes) || maxLineBytes < 1 || maxLineBytes > MAX_FRAME_BYTES) {
      throw new TerminalInputControllerError(
        `maxLineBytes must be a positive integer <= ${MAX_FRAME_BYTES}`,
      );
    }
    this.maxLineBytes = maxLineBytes;
  }

  /** Feed one text chunk and return every complete line found in it. */
  feed(chunk: string): string[] {
    this.requireOpen();
    if (typeof chunk !== "string") {
      throw new TerminalInputControllerError("input chunk must be text");
    }

    const lines: string[] = [];
    let start = 0;
    if (this.skipLfAfterCr) {
      if (chunk.length === 0) return lines;
      if (chunk.startsWith("\n")) start = 1;
      this.skipLfAfterCr = false;
    }

    while (start < chunk.length) {
      const nextLf = chunk.indexOf("\n", start);
      const nextCr = chunk.indexOf("\r", start);
      const delimiter = nextLf < 0
        ? nextCr
        : nextCr < 0
          ? nextLf
          : Math.min(nextLf, nextCr);

      if (delimiter < 0) {
        this.append(chunk.slice(start));
        break;
      }

      this.append(chunk.slice(start, delimiter));
      lines.push(this.takeLine());
      if (chunk[delimiter] === "\r") {
        this.skipLfAfterCr = true;
        if (chunk[delimiter + 1] === "\n") {
          start = delimiter + 2;
          this.skipLfAfterCr = false;
          continue;
        }
      }
      start = delimiter + 1;
    }
    return lines;
  }

  /**
   * Flush a final unterminated line and close the controller.
   *
   * A trailing delimiter has already emitted its line, so EOF does not create
   * an additional empty record.
   */
  finish(): string[] {
    this.requireOpen();
    this.finished = true;
    this.skipLfAfterCr = false;
    if (!this.buffer) return [];
    return [this.takeLine()];
  }

  /** Reset framing state so a frontend can start a fresh input stream. */
  reset(): void {
    this.buffer = "";
    this.bufferedBytes = 0;
    this.skipLfAfterCr = false;
    this.finished = false;
  }

  /** Return detached state without exposing mutable internals. */
  snapshot(): TerminalInputSnapshot {
    return {
      buffer: this.buffer,
      buffered_bytes: this.bufferedBytes,
      finished: this.finished,
    };
  }

  private append(segment: string): void {
    if (!segment) return;
    const segmentBytes = byteLength(segment);
    const nextBytes = joinedByteLength(this.buffer, this.bufferedBytes, segment, segmentBytes);
    if (nextBytes > this.maxLineBytes) {
      this.buffer = "";
      this.bufferedBytes = 0;
      throw new TerminalInputControllerError(
        `input line exceeds ${this.maxLineBytes} UTF-8 bytes`,
      );
    }
    this.buffer += segment;
    this.bufferedBytes = nextBytes;
  }

  private takeLine(): string {
    const line = this.buffer;
    this.buffer = "";
    this.bufferedBytes = 0;
    return line;
  }

  private requireOpen(): void {
    if (this.finished) {
      throw new TerminalInputControllerError("input controller is finished; call reset() before feeding");
    }
  }
}
