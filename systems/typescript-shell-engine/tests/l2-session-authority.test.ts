import { describe, expect, it } from "vitest";
import { makeMessage } from "../src/protocol/wire-envelope.ts";
import {
  L2SessionAuthority,
  L2SessionAuthorityError,
} from "../src/engine/l2-session-authority.ts";

function event(sessionId: string, seq: number, value: number) {
  return makeMessage(sessionId, seq, "event", { value }, `trace-${seq}`, seq);
}

describe("L2 authoritative session data boundary", () => {
  it("holds out-of-order reservations until the committed sequence is contiguous", () => {
    const authority = new L2SessionAuthority({ outboxMaxlen: 4 });
    expect(authority.next("session-1")).toBe(1);
    expect(authority.next("session-1")).toBe(2);

    authority.publish(event("session-1", 2, 2));
    expect(authority.replay("session-1")).toEqual([]);
    expect(authority.snapshot("session-1")).toMatchObject({
      nextSequence: 3,
      nextCommittedSequence: 1,
      pendingMessages: 1,
    });

    authority.publish(event("session-1", 1, 1));
    expect(authority.replay("session-1").map((message) => message.seq)).toEqual([1, 2]);
    expect(authority.snapshot("session-1")).toMatchObject({
      nextCommittedSequence: 3,
      pendingMessages: 0,
      oldestSequence: 1,
      latestSequence: 2,
    });
  });

  it("keeps per-view acknowledgements non-destructive and survives detach/reattach", () => {
    const authority = new L2SessionAuthority();
    authority.attach("session-1", "view-a");
    authority.attach("session-1", "view-b");
    const first = authority.next("session-1");
    const second = authority.next("session-1");
    authority.publish(event("session-1", first, 1));
    authority.publish(event("session-1", second, 2));

    authority.ack("session-1", "view-a", 1);
    expect(authority.replay("session-1", "view-a").map((message) => message.seq)).toEqual([2]);
    expect(authority.replay("session-1", "view-b").map((message) => message.seq)).toEqual([1, 2]);

    expect(authority.detach("session-1", "view-a")).toBe(true);
    expect(() => authority.replay("session-1", "view-a")).toThrow(L2SessionAuthorityError);
    authority.attach("session-1", "view-a");
    expect(authority.replay("session-1", "view-a").map((message) => message.seq)).toEqual([2]);
  });

  it("bounds retained messages and returns detached copies", () => {
    const authority = new L2SessionAuthority({ outboxMaxlen: 2 });
    for (const value of [1, 2, 3]) {
      const sequence = authority.next("session-1");
      authority.publish(event("session-1", sequence, value));
    }

    const replay = authority.replay("session-1");
    expect(replay.map((message) => message.seq)).toEqual([2, 3]);
    replay[0]!.payload.value = 99;
    expect(authority.replay("session-1")[0]!.payload.value).toBe(2);
    expect(authority.snapshot("session-1")).toMatchObject({
      retainedMessages: 2,
      oldestSequence: 2,
      latestSequence: 3,
    });
  });

  it("fails closed on unreserved, conflicting, stale, and detached operations", () => {
    const authority = new L2SessionAuthority({ outboxMaxlen: 1 });
    expect(() => authority.publish(event("session-1", 2, 2))).toThrow(/not reserved/);

    const sequence = authority.next("session-1");
    const first = event("session-1", sequence, 1);
    authority.publish(first);
    authority.publish(first);
    expect(() => authority.publish(event("session-1", sequence, 9))).toThrow(/already committed|conflicting/);

    const secondSequence = authority.next("session-1");
    authority.publish(event("session-1", secondSequence, 2));
    expect(() => authority.publish(first)).toThrow(/already committed or evicted/);
    expect(() => authority.ack("session-1", "view-a", 1)).toThrow(/not attached/);
  });

  it("bounds tracked sessions and can clear volatile state", () => {
    const authority = new L2SessionAuthority({ maxSessions: 1 });
    authority.next("session-a");
    expect(() => authority.next("session-b")).toThrow(/bound exceeded/);
    expect(authority.clear("session-a")).toBe(true);
    expect(authority.next("session-b")).toBe(1);
    expect(authority.clear("session-b")).toBe(true);
    expect(authority.snapshot("session-b")).toBeNull();
  });
});
