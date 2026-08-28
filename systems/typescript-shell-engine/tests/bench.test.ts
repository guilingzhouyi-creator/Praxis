/**
 * Performance baseline tests — hot path regression detection.
 * These are informational (always pass) but record ops/sec in verbose output
 * for trend tracking via `vitest run --reporter=verbose | grep ops/s`.
 */

import { describe, it } from "vitest";
import { bench } from "../src/engine/bench.ts";
import { tokenize, parseLine } from "../src/engine/parser.ts";
import { Dispatcher } from "../src/engine/dispatcher.ts";
import { parseRoute } from "../src/engine/route.ts";
import { parseCommandCatalog } from "../src/engine/command-catalog.ts";
import { SessionMultiplexer } from "../src/engine/session-manager.ts";
import { Outbox, makeMessage } from "../src/wire-envelope.ts";

/** Tiny commands.yaml subset shared by the catalog benchmarks. */
const CATALOG_YAML = `
help:
  category: session
  help: "Show available commands"
agents:
  category: session
  help: "List all agents"
  aliases: ["ls"]
connect:
  category: session
  help: "Connect to an agent (direct mode)"
  args:
    - {name: agent_id, completer: agent, description: "Target agent ID"}
  examples:
    - "/connect agent-writer — connect to an agent"
`;

describe("perf baselines", () => {
  it("tokenize: simple tokens", () => {
    const input = "status --verbose --format json arg1 arg2 arg3";
    const r = bench("tokenize-simple", () => void tokenize(input));
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });

  it("tokenize: quoted args", () => {
    const input = 'deploy "my project" --env "production" --tag v2';
    const r = bench("tokenize-quoted", () => void tokenize(input));
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });

  it("parseLine: full pipeline", () => {
    const r = bench("parseLine", () => void parseLine("status --verbose arg"));
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });

  it("dispatcher: registered command lookup", () => {
    const d = new Dispatcher();
    d.register("lang", () => ({ kind: "local" as const, data: {} }));
    d.register("help", () => ({ kind: "local" as const, data: {} }));
    d.register("clear", () => ({ kind: "local" as const, data: {} }));
    const ctx = { sessionId: "bench" };
    const r = bench("dispatch-registered", () =>
      void d.dispatch({ name: "lang", args: [] }, ctx),
    );
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });

  it("outbox: append at capacity (ring buffer)", () => {
    const outbox = new Outbox(1024);
    // Pre-fill to capacity so appends trigger ring-buffer overwrite.
    for (let i = 0; i < 1024; i++) {
      outbox.append(makeMessage("bench", i, "event", { data: `msg-${i}` }));
    }
    let seq = 1024;
    const r = bench("outbox-append-at-capacity", () => {
      outbox.append(makeMessage("bench", seq++, "event", { data: "x" }));
    });
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });

  it("envelope: encode+decode roundtrip", () => {
    const msg = makeMessage("bench-sess", 42, "command", { name: "status", args: ["--json"] }, "trace-1");
    const encoded = JSON.stringify(msg);
    const r = bench("encode-decode-roundtrip", () => {
      const line = JSON.stringify(msg);
      const parsed = JSON.parse(line);
      return parsed;
    });
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });

  // ── Phase A hot paths (2026-08-28) ─────────────────────────────────

  it("route: dialect classification of engine/system/tool lines", () => {
    const lines = ["/status --json", "$ls -la", "read_file a.txt", "just an intent"];
    let i = 0;
    const r = bench("route-classify", () => {
      void parseRoute(lines[i++ % lines.length]);
    });
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });

  it("command-catalog: YAML reload + alias resolution", () => {
    const catalog = parseCommandCatalog(CATALOG_YAML);
    const r = bench("catalog-alias-lookup", () => {
      void catalog.resolveAlias("ls");
    });
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
    const reload = bench("catalog-yaml-reload", () => {
      catalog.loadDefaults(CATALOG_YAML);
    });
    console.log(`ops/s: ${reload.name} ${reload.opsPerSec}`);
  });

  it("session-mux: emit + per-view ack", () => {
    const mux = new SessionMultiplexer("bench");
    mux.attach("web");
    mux.attach("tui");
    let seq = 1;
    const r = bench("session-mux-emit-ack", () => {
      mux.emit(makeMessage("bench", seq, "event", { data: "x" }));
      mux.ack("web", seq);
      mux.ack("tui", seq);
      seq++;
    });
    console.log(`ops/s: ${r.name} ${r.opsPerSec}`);
  });
});
