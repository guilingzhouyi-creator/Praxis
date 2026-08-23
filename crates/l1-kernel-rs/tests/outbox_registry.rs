//! Per-session outbox registry integration tests: lazy session isolation,
//! non-destructive per-view replay windows, exact eviction counting, metrics
//! across teardown, and interleaved multi-view attach/ack/replay stress.

use std::collections::{BTreeMap, HashMap};

use l1_kernel_rs::outbox_registry::OutboxRegistry;
use l1_kernel_rs::protocol::{Message, MessageKind};
use serde_json::json;

fn msg(session_id: &str, seq: u64) -> Message {
    Message::new(
        session_id,
        seq,
        MessageKind::Event,
        BTreeMap::from([("event_type".to_owned(), json!("tick"))]),
        "",
        0.0,
    )
}

fn seqs(messages: Vec<Message>) -> Vec<u64> {
    messages.into_iter().map(|message| message.seq).collect()
}

#[test]
fn sessions_are_lazily_created_and_isolated() {
    let mut registry = OutboxRegistry::new();
    assert!(registry.session_ids().is_empty());
    for seq in 1..=3 {
        registry.append("s-1", msg("s-1", seq));
    }
    for seq in 1..=2 {
        registry.append("s-2", msg("s-2", seq));
    }
    // The same sequences in different sessions never collide.
    assert_eq!(seqs(registry.get_or_create("s-1").unacked_after(-1)), [1, 2, 3]);
    assert_eq!(seqs(registry.get_or_create("s-2").unacked_after(-1)), [1, 2]);
    // Enumerated in stable sorted order.
    assert_eq!(registry.session_ids(), ["s-1", "s-2"]);
}

#[test]
fn view_acks_never_erase_other_view_replay_windows() {
    let mut registry = OutboxRegistry::new();
    registry.attach("s-1", "view-a");
    registry.attach("s-1", "view-b");
    for seq in 1..=5 {
        registry.append("s-1", msg("s-1", seq));
    }
    // View A races ahead; view B (still at -1) must keep its full window.
    registry.ack_view("s-1", "view-a", 4);
    assert_eq!(
        seqs(registry.replay("s-1", "view-b", -1)),
        [1, 2, 3, 4, 5],
        "view B replay window must survive view A ack"
    );
    // View A only sees messages past its own cursor.
    assert_eq!(seqs(registry.replay("s-1", "view-a", -1)), [5]);
    // after_seq narrows a view's window on top of its cursor.
    assert_eq!(seqs(registry.replay("s-1", "view-b", 2)), [3, 4, 5]);
    // The shared session buffer itself is untouched by view acks.
    assert_eq!(
        seqs(registry.get_or_create("s-1").unacked_after(-1)),
        [1, 2, 3, 4, 5]
    );
}

#[test]
fn eviction_beyond_maxlen_drops_oldest_and_counts_exactly() {
    let mut registry = OutboxRegistry::with_maxlen(2).expect("capacity");
    for seq in 1..=5 {
        registry.append("s-1", msg("s-1", seq));
    }
    assert_eq!(seqs(registry.get_or_create("s-1").unacked_after(-1)), [4, 5]);
    let metrics = registry.metrics();
    assert_eq!(metrics.appended_total, 5);
    assert_eq!(metrics.evicted_total, 3);
    assert_eq!(metrics.live_sessions, 1);
    assert_eq!(metrics.live_views, 0);
}

#[test]
fn metrics_track_acks_and_live_counts_across_teardown() {
    let mut registry = OutboxRegistry::new();
    registry.append("s-1", msg("s-1", 1));
    registry.append("s-1", msg("s-1", 2));
    registry.append("s-2", msg("s-2", 1));
    registry.attach("s-1", "view-a");
    registry.attach("s-1", "view-b");
    registry.attach("s-2", "view-c");

    registry.ack("s-1", 1);
    registry.ack_view("s-1", "view-a", 2);
    registry.ack_view("s-1", "view-b", 2);

    let metrics = registry.metrics();
    assert_eq!(metrics.appended_total, 3);
    assert_eq!(metrics.evicted_total, 0);
    assert_eq!(metrics.acks_total, 3);
    assert_eq!(metrics.live_sessions, 2);
    assert_eq!(metrics.live_views, 3);

    // Unknown views are a no-op: no cursor, no counter bump.
    registry.ack_view("s-1", "ghost", 9);
    assert!(registry.cursor("s-1", "ghost").is_none());
    assert_eq!(registry.metrics().acks_total, 3);

    // Detach retains the cursor but the view leaves the live count.
    registry.detach("s-1", "view-a");
    assert_eq!(
        registry.cursor("s-1", "view-a").map(|cursor| cursor.last_acked),
        Some(2)
    );
    assert_eq!(registry.metrics().live_views, 2);
    // A detached-but-retained cursor still advances monotonically.
    registry.ack_view("s-1", "view-a", 3);
    assert_eq!(
        registry.cursor("s-1", "view-a").map(|cursor| cursor.last_acked),
        Some(3)
    );
    assert_eq!(registry.metrics().acks_total, 4);

    // Removing a session drops its outbox and its views together.
    registry.remove("s-1");
    assert_eq!(registry.metrics().live_sessions, 1);
    assert_eq!(registry.metrics().live_views, 1);
    assert!(registry.cursor("s-1", "view-b").is_none());
    assert_eq!(registry.watermark("s-1"), -1);
    assert_eq!(registry.session_ids(), ["s-2"]);

    // Sessions re-materialize lazily after teardown.
    registry.append("s-1", msg("s-1", 42));
    assert_eq!(seqs(registry.get_or_create("s-1").unacked_after(-1)), [42]);
}

#[test]
fn concurrent_attach_ack_replay_stress_preserves_invariants() {
    let mut registry = OutboxRegistry::with_maxlen(16).expect("capacity");
    let views = ["view-a", "view-b", "view-c"];
    let mut max_acked: HashMap<(String, String), i64> = HashMap::new();
    for session in 1..=5 {
        let sid = format!("s-{session}");
        for view in views.iter() {
            registry.attach(&sid, view);
            max_acked.insert((sid.clone(), view.to_string()), -1);
        }
    }
    for round in 0u64..1000 {
        let sid = format!("s-{}", (round % 5) + 1);
        registry.append(&sid, msg(&sid, round));
        // Interleaved view activity: each view acks a different horizon.
        for (index, view) in views.iter().enumerate() {
            let horizon = match index {
                0 => round,
                1 => round.saturating_sub(2),
                _ => round.saturating_sub(4),
            };
            registry.ack_view(&sid, view, horizon);
            let entry = max_acked.entry((sid.clone(), view.to_string())).or_insert(-1);
            *entry = (*entry).max(i64::try_from(horizon).unwrap_or(i64::MAX));
        }
        if round % 50 == 0 {
            for session in 1..=5 {
                let sid = format!("s-{session}");
                if registry.session_ids().contains(&sid) {
                    assert!(
                        registry.get_or_create(&sid).len() <= 16,
                        "buffer stays bounded for {sid}"
                    );
                }
                let mut lowest = i64::MAX;
                for view in views.iter() {
                    let cursor = registry.cursor(&sid, view).expect("attached view cursor");
                    assert_eq!(
                        cursor.last_acked,
                        max_acked[&(sid.clone(), view.to_string())],
                        "cursor equals the max ack issued for {sid}/{view}"
                    );
                    lowest = lowest.min(cursor.last_acked);
                }
                assert_eq!(registry.watermark(&sid), lowest, "watermark is the laggard");
                for view in views.iter() {
                    let cursor = registry.cursor(&sid, view).expect("attached view cursor");
                    let window = seqs(registry.replay(&sid, view, -1));
                    assert!(
                        window
                            .iter()
                            .all(|value| i64::try_from(*value).unwrap_or(i64::MAX) > cursor.last_acked),
                        "replay stays strictly past the view cursor for {sid}/{view}"
                    );
                }
            }
        }
    }
    // Exact bookkeeping after the storm: 1000 appends, 3 view acks each.
    let metrics = registry.metrics();
    assert_eq!(metrics.appended_total, 1000);
    assert_eq!(metrics.acks_total, 3000);
    // Each session holds 200 messages in a window of 16 -> 184 evictions each.
    assert_eq!(metrics.evicted_total, 5 * (200 - 16));
    assert_eq!(metrics.live_sessions, 5);
    assert_eq!(metrics.live_views, 15);
}