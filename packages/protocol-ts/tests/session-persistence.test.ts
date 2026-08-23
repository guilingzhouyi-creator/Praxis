import { describe, it, expect } from "vitest";
import { InMemorySessionPersistence } from "../src/engine/session-persistence.ts";
import type { SessionSnapshot } from "../src/engine/session-persistence.ts";

function snap(id: string): SessionSnapshot {
  return {
    session_id: id,
    title: "t",
    status: "active",
    turn_count: 1,
    card_count: 2,
    user_id: "u",
    memory_scope: "m",
    cell_id: "c",
    role: "r",
    model_config: { provider: "test" },
  };
}

describe("InMemorySessionPersistence", () => {
  it("save/load/list/remove", async () => {
    const store = new InMemorySessionPersistence();
    await store.save(snap("s-1"));
    await store.save(snap("s-2"));
    expect(await store.list()).toEqual(expect.arrayContaining(["s-1", "s-2"]));
    expect((await store.load("s-1"))?.session_id).toBe("s-1");
    await store.remove("s-1");
    expect(await store.load("s-1")).toBeUndefined();
    expect(await store.list()).toEqual(["s-2"]);
  });

  it("envelopeOf checksum is deterministic", () => {
    const s = snap("s-x");
    const e1 = InMemorySessionPersistence.envelopeOf(s);
    const e2 = InMemorySessionPersistence.envelopeOf(s);
    expect(e1.checksum).toBe(e2.checksum);
    expect(e1.v).toBe(1);
    expect(e1.kind).toBe("session_snapshot");
  });
});
