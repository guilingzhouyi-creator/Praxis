/**
 * ShellSession tests — per-session mode and routing identity.
 */

import { describe, expect, it } from "vitest";
import { ShellSession } from "../src/engine/routing-session.ts";

describe("ShellSession", () => {
  it("starts in L3A mode with detached identities", () => {
    const session = new ShellSession({ shell: "terminal", sessionId: "s-1" });
    expect(session.isDirect()).toBe(false);
    expect(session.asDict()).toEqual({
      shell: "terminal",
      mode: "L3A",
      cell_id: "",
      agent_id: "",
      session_id: "s-1",
    });
  });

  it("switches to a direct Cell/Agent target and back", () => {
    const session = new ShellSession({ shell: "terminal", sessionId: "s-1" });
    session.switchToDirect("cell-a", "agent-a", "s-2");
    expect(session.isDirect()).toBe(true);
    expect(session.asDict()).toMatchObject({
      mode: "DIRECT",
      cell_id: "cell-a",
      agent_id: "agent-a",
      session_id: "s-2",
    });

    session.switchToL3A();
    expect(session.isDirect()).toBe(false);
    expect(session.asDict()).toMatchObject({ mode: "L3A", agent_id: "", session_id: "" });
  });

  it("rejects an invalid direct-mode construction without an agent", () => {
    const session = new ShellSession({ mode: "DIRECT", shell: "terminal" });
    expect(session.asDict().mode).toBe("L3A");
    expect(session.isDirect()).toBe(false);
  });
});
